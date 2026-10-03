"""来信台账 DAL（v2.0.0 存储层）：inbox_mails 表，替代旧 inbox.jsonl 追加文件。

设计取舍（对照 lightcloudmaster/mail_store.py::InboxStore，公开 API 1:1、调用方零改动）：
- 旧实现把整封 mail dict 原样写 JSONL；本 DAL 只落 ReceivedMail.to_record() 的 9 列
  （uid/kind/from_addr/subject/date/ticket/body/stop_requested/fetched_at），其余键忽略：
  落库字段收口成白名单，正文截断等隐私边界仍由写入方（inbox.parse_message）负责。
- 重复 uid：旧实现"读全量文件→集合比对"（O(n) 且并发有竞态），改为主键 + INSERT OR IGNORE，
  在连接锁之外再加一层库级唯一性保证；rowcount==0 即冲突，返回值与旧完全一致。
- list_recent 按 rowid 倒取最后 limit 条再反转，保持追加序（旧 JSONL `[-limit:]` 语义）。
- 布尔列 stop_requested 写 int(bool(...))、读 bool(...)，对外仍是 Python bool。
- 路径经 db.resolve_db_path 收口（INBOX_DB_PATH 与旧环境变量同名，conftest 隔离机制不变）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from . import db


class MailStoreError(ValueError):
    """来信/报告台账参数错误（自包含复制自旧 mail_store.MailStoreError，P3 删旧模块）。"""


def _text(mail: dict[str, Any], key: str) -> str:
    """取文本列：缺失/None 归一为空串（列 NOT NULL；旧 JSON 允许缺键，读回语义取 ''）。"""
    value = mail.get(key)
    return "" if value is None else str(value)


def _row_to_mail(row: sqlite3.Row) -> dict[str, Any]:
    """行 → 来信 dict：键集与 to_record() 的 9 键一致，stop_requested 读回 bool。"""
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
        # 与旧 store 一致：父目录不存在则创建（缺省 data/private 可能尚未建）。
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
            if cur.rowcount == 0:  # 主键冲突被 IGNORE，与旧"重复 uid 跳过"同语义
                return {"recorded": False, "reason": "duplicate uid"}
        return {"recorded": True, "uid": uid}

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """最近 limit 封，按追加序返回（rowid 倒取再反转，等价旧 `[-limit:]`）。"""
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
