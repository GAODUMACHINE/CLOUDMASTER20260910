"""次日温和回访队列 DAL：followups 表。

approve 裁决时 enqueue（services.crisis_chain.enqueue_followup），到期由
jobs/followups.run_due 扫描交付。done = 已交付审核台待办区，而非回访已完成：
回访本身是线下人工动作（系统不代打电话、不催办），系统职责是可见性而非执行。
红线：不落任何联系方式与对话内容；anon_key 仅用于值班员核对。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import db

# 队列状态词表（DDL CHECK 同款）：pending=待到期 / done=已交付待办区 / skipped=跳过。
FOLLOWUP_STATUSES = ("pending", "done", "skipped")


class FollowupQueue:
    """回访队列（统一业务库 followups 表，经 storage.db 共享连接与锁）。"""

    def __init__(self, path: str | None = None):
        self._path: Path = db.resolve_db_path(path, "FOLLOWUP_DB_PATH")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn, self._lock = db.connect(self._path)

    @property
    def path(self) -> Path:
        return self._path

    @staticmethod
    def _row_of(r: Any) -> dict[str, Any]:
        return {
            "id": r["id"],
            "ticket_id": r["ticket_id"],
            "anon_key": r["anon_key"],
            "scheduled_at": r["scheduled_at"],
            "kind": r["kind"],
            "status": r["status"],
        }

    def enqueue(
        self,
        *,
        ticket_id: str,
        anon_key: str,
        scheduled_at: str,
        kind: str = "次日温和回访",
    ) -> dict[str, Any]:
        """入队一条回访（status=pending）。同工单重复入队不去重——重开路径里旧条目
        已翻状态，新条目即最新计划。"""
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO followups (ticket_id, anon_key, scheduled_at, kind, status)"
                " VALUES (?, ?, ?, ?, 'pending')",
                (ticket_id, anon_key, scheduled_at, kind),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT id, ticket_id, anon_key, scheduled_at, kind, status FROM followups WHERE id = ?",
                (cur.lastrowid,),
            ).fetchone()
        return self._row_of(row)

    def due(self, *, now: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """到期待交付条目（pending 且 scheduled_at <= now），按计划时间升序。"""
        moment = now or db.now_iso()
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, ticket_id, anon_key, scheduled_at, kind, status FROM followups"
                " WHERE status = 'pending' AND scheduled_at <= ? ORDER BY scheduled_at LIMIT ?",
                (moment, limit),
            ).fetchall()
        return [self._row_of(r) for r in rows]

    def mark_done(self, followup_id: int) -> dict[str, Any] | None:
        """交付（pending→done）；不存在或非 pending 返回 None（幂等重跑安全）。"""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE followups SET status = 'done' WHERE id = ? AND status = 'pending'",
                (followup_id,),
            )
            if cur.rowcount != 1:
                self._conn.rollback()
                return None
            row = self._conn.execute(
                "SELECT id, ticket_id, anon_key, scheduled_at, kind, status FROM followups WHERE id = ?",
                (followup_id,),
            ).fetchone()
            self._conn.commit()
        return self._row_of(row)

    def mark_skipped(self, followup_id: int) -> dict[str, Any] | None:
        """跳过（pending→skipped）：值班员判断不宜回访（如用户已注销）时使用。"""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE followups SET status = 'skipped' WHERE id = ? AND status = 'pending'",
                (followup_id,),
            )
            if cur.rowcount != 1:
                self._conn.rollback()
                return None
            row = self._conn.execute(
                "SELECT id, ticket_id, anon_key, scheduled_at, kind, status FROM followups WHERE id = ?",
                (followup_id,),
            ).fetchone()
            self._conn.commit()
        return self._row_of(row)

    def pending_count(self) -> int:
        """待到期数量。"""
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM followups WHERE status = 'pending'").fetchone()
        return int(row[0])

    def delivered_recent(self, *, days: int = 7) -> list[dict[str, Any]]:
        """已交付条目（status=done），新近优先，至多 50 条——审核台回访待办区数据源。

        days 为保留的签名参数：表无 done_at 列无法按时间过滤；需要更严窗口时可
        自行按 scheduled_at 截断。
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, ticket_id, anon_key, scheduled_at, kind, status FROM followups"
                " WHERE status = 'done' ORDER BY id DESC LIMIT 50"
            ).fetchall()
        return [self._row_of(r) for r in rows]
