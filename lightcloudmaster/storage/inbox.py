"""来信台账 DAL：inbox_mails 表。

只落 9 列白名单（uid/kind/from_addr/subject/date/ticket/body/stop_requested/
fetched_at），正文截断等隐私边界由写入方（services.mail.parse）负责。
重复 uid 靠主键 + INSERT OR IGNORE 拦截；list_recent 按 rowid 倒取再反转保持追加序。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from . import db


class MailStoreError(ValueError):
    """来信/报告台账参数错误。"""


def _text(mail: dict[str, Any], key: str) -> str:
    """取文本列：缺失/None 归一为空串（列 NOT NULL）。"""
    value = mail.get(key)
    return "" if value is None else str(value)


def _row_to_mail(row: sqlite3.Row) -> dict[str, Any]:
    """行 → 来信 dict：与 to_record() 的 9 键一致，stop_requested 读回 bool。"""
    return {
        "uid": row["uid"],
        "kind": row["kind"],
        "from_addr": row["from_addr"],
        "subject": row["subject"],
        "date": row["date"],
        "ticket": row["ticket"],
        "body": row["body"],
        "stop_requested": bool(row["stop_requested"]),
        "fetched_at": row["fetched_at"],
    }


class InboxStore:
    """来信台账：append-only，可审计；同一 uid 不重复入库。"""

    def __init__(self, path: str | None = None):
        self._path = db.resolve_db_path(path, "INBOX_DB_PATH")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn, self._lock = db.connect(self._path)

    @property
    def path(self) -> Path:
        return self._path

    def known_uids(self) -> set[str]:
        with self._lock:
            rows = self._conn.execute("SELECT uid FROM inbox_mails").fetchall()
        return {str(r["uid"]) for r in rows}

    def record(self, mail: dict[str, Any]) -> dict[str, Any]:
        """写入一封来信；缺 uid 或重复 uid 则拒绝/跳过。"""
        uid = str(mail.get("uid") or "").strip()
        if not uid:
            raise MailStoreError("来信缺少 uid")
        with self._lock:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO inbox_mails"
                " (uid, kind, from_addr, subject, date, ticket, body,"
                " stop_requested, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    uid,
                    _text(mail, "kind"),
                    _text(mail, "from_addr"),
                    _text(mail, "subject"),
                    _text(mail, "date"),
                    _text(mail, "ticket"),
                    _text(mail, "body"),
                    int(bool(mail.get("stop_requested"))),
                    _text(mail, "fetched_at"),
                ),
            )
            self._conn.commit()
            if cur.rowcount == 0:  # 主键冲突被 IGNORE，重复 uid 跳过
                return {"recorded": False, "reason": "duplicate uid"}
        return {"recorded": True, "uid": uid}

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """最近 limit 封，按追加序返回。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT uid, kind, from_addr, subject, date, ticket, body,"
                " stop_requested, fetched_at FROM inbox_mails ORDER BY rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_mail(r) for r in reversed(rows)]

    def by_ticket(self, ticket: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT uid, kind, from_addr, subject, date, ticket, body,"
                " stop_requested, fetched_at FROM inbox_mails WHERE ticket = ? ORDER BY rowid",
                (ticket,),
            ).fetchall()
        return [_row_to_mail(r) for r in rows]

    def count(self) -> int:
        with self._lock:
            (total,) = self._conn.execute("SELECT COUNT(*) FROM inbox_mails").fetchone()
        return int(total)
