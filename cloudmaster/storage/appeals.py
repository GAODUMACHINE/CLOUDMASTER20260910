"""申诉与投诉举报受理 DAL（《办法》第 21 条；TC-PRIV-006 / TC-RES-002）——SQLite 版。

设计取舍（v2.0.0 存储层 P1）：
- 公开 API 与旧 cloudmaster/appeals.py 完全一致：类名 / 方法签名 / AppealError 与
  中文错误文案 / 返回 dict 的键序与语义，调用方零改动切换；APPEAL_KINDS 复制进
  本模块使其自包含（旧模块 P3 才删，暂时允许重复）。
- 落库为统一业务库 business.db 的 appeals 表（db.py §16 DDL）；旧 JSONL「逐行追加」
  语义 ≙ INSERT——append-only、并发安全（每库一连接 + RLock 串行化）。
- appeal_events 表（受理后的处置轨迹）**本阶段不启用 DAL，P4 启用**：表结构已在
  db.py 先行落地，此处不留占位方法，避免过早暴露未定契约。
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
            self._conn.commit()
        return record

    def count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM appeals").fetchone()
        return int(row[0])
