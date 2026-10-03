"""申诉与投诉举报受理 DAL（《办法》第 21 条；TC-PRIV-006 / TC-RES-002）——SQLite 版。

设计取舍（v2.0.0 存储层 P1）：
- 公开 API 与旧 lightcloudmaster/appeals.py 完全一致：类名 / 方法签名 / AppealError 与
  中文错误文案 / 返回 dict 的键序与语义，调用方零改动切换；APPEAL_KINDS 复制进
  本模块使其自包含（旧模块 P3 才删，暂时允许重复）。
- 落库为统一业务库 business.db 的 appeals 表（db.py §16 DDL）；旧 JSONL「逐行追加」
  语义 ≙ INSERT——append-only、并发安全（每库一连接 + RLock 串行化）。
- appeal_events 表（受理后的处置轨迹）自 v2.0.0 P4 起启用：submit 同事务落 received
  事件（受理即留痕）；add_event 追加处置动作（processing/resolved/rejected 同步翻
  appeals.status，received 只记事件不改状态——「已受理」是提交即成立的事实）。
  当前无 API 路由消费处置轨迹（24 路由清单封闭），add_event/events/list_open 是
  运维/后续界面通道——能力先落库，红线是事件只记动作与备注、不落任何对话内容。
- 隐私最小化红线不变：仅记录申诉所需最小字段，不含姓名/联系方式。
- 约定：SQL 一律 ? 参数化；写方法 with self._lock: 执行 + conn.commit()；
  时间戳一律 db.now_iso()；本模块无布尔列。
"""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from . import db

# 申诉类型词表（键=前端提交值，值=台账展示文案）。
APPEAL_KINDS = {
    "minor_misjudged": "未成年人模式误判申诉",
    "content": "内容与回复问题投诉",
    "privacy": "隐私与数据使用投诉",
    "other": "其他投诉与举报",
}

# 处置动作词表（appeal_events.action）：received 由 submit 自动落，其余由处置方经
# add_event 写入；processing/resolved/rejected 会同步翻转 appeals.status。
APPEAL_ACTIONS = {
    "received": "已受理",
    "processing": "处理中",
    "resolved": "已办结",
    "rejected": "不予受理（附理由）",
}


class AppealError(ValueError):
    pass


class AppealStore:
    """append-only 申诉受理台账（SQLite）；可审计、可闭环。"""

    def __init__(self, path: str | None = None):
        self._path = db.resolve_db_path(path, "APPEAL_DB_PATH")
        # 与旧 store 一致：初始化即确保父目录存在（缺省 data/private 可能尚未创建），
        # 再取进程级共享连接与锁（同一 business.db 全 DAL 复用一条连接）。
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn, self._lock = db.connect(self._path)

    @property
    def path(self) -> Path:
        return self._path

    def submit(self, kind: str, text: str, profile_key: str = "") -> dict[str, Any]:
        if kind not in APPEAL_KINDS:
            raise AppealError(f"不支持的申诉类型: {kind}")
        body = (text or "").strip()
        if not body:
            raise AppealError("申诉内容不能为空")
        record = {
            "ticket_id": "AP-" + secrets.token_hex(6),
            "submitted_at": db.now_iso(),
            "kind": kind,
            "kind_label": APPEAL_KINDS[kind],
            "text": body[:2000],
            "profile_key": profile_key,
            "status": "received",
        }
        with self._lock:
            self._conn.execute(
                "INSERT INTO appeals (ticket_id, submitted_at, kind, kind_label, text,"
                " profile_key, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    record["ticket_id"],
                    record["submitted_at"],
                    record["kind"],
                    record["kind_label"],
                    record["text"],
                    record["profile_key"],
                    record["status"],
                ),
            )
            # 受理即留痕：received 事件与工单同一事务落库（提交不可能「无痕受理」）。
            self._conn.execute(
                "INSERT INTO appeal_events (ticket_id, action, actor, note, acted_at) VALUES (?, ?, ?, ?, ?)",
                (record["ticket_id"], "received", "system", "申诉提交入库", record["submitted_at"]),
            )
            self._conn.commit()
        return record

    def add_event(self, ticket_id: str, action: str, *, actor: str = "", note: str = "") -> dict[str, Any]:
        """追加处置事件；processing/resolved/rejected 同步翻转工单状态（同事务）。

        工单不存在时报错（不允许给幽灵工单造轨迹）；received 只记事件——它由 submit
        自动产生，人工重放不改变「已受理」这一既成事实。
        """
        if action not in APPEAL_ACTIONS:
            raise AppealError(f"不支持的申诉处置动作: {action}")
        acted_at = db.now_iso()
        with self._lock:
            row = self._conn.execute(
                "SELECT ticket_id FROM appeals WHERE ticket_id = ?", (ticket_id,)
            ).fetchone()
            if row is None:
                raise AppealError("申诉工单不存在")
            self._conn.execute(
                "INSERT INTO appeal_events (ticket_id, action, actor, note, acted_at) VALUES (?, ?, ?, ?, ?)",
                (ticket_id, action, actor, note[:500], acted_at),
            )
            if action != "received":
                self._conn.execute("UPDATE appeals SET status = ? WHERE ticket_id = ?", (action, ticket_id))
            self._conn.commit()
        return {
            "ticket_id": ticket_id,
            "action": action,
            "action_label": APPEAL_ACTIONS[action],
            "actor": actor,
            "note": note[:500],
            "acted_at": acted_at,
        }

    def events(self, ticket_id: str) -> list[dict[str, Any]]:
        """该工单的处置轨迹（按事件序）——处理进度对用户/监管可解释的依据。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, ticket_id, action, actor, note, acted_at FROM appeal_events"
                " WHERE ticket_id = ? ORDER BY id",
                (ticket_id,),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "ticket_id": r["ticket_id"],
                "action": r["action"],
                "actor": r["actor"],
                "note": r["note"],
                "acted_at": r["acted_at"],
            }
            for r in rows
        ]

    def list_open(self) -> list[dict[str, Any]]:
        """未办结申诉（status 非 resolved/rejected），按受理序——运营处置队列视图。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT ticket_id, submitted_at, kind, kind_label, text, profile_key, status"
                " FROM appeals WHERE status NOT IN ('resolved', 'rejected') ORDER BY rowid"
            ).fetchall()
        return [
            {
                "ticket_id": r["ticket_id"],
                "submitted_at": r["submitted_at"],
                "kind": r["kind"],
                "kind_label": r["kind_label"],
                "text": r["text"],
                "profile_key": r["profile_key"],
                "status": r["status"],
            }
            for r in rows
        ]

    def count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM appeals").fetchone()
        return int(row[0])
