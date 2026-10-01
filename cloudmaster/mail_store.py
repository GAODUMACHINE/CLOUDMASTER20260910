"""邮件报告与来信台账（ADR-009）。

- 报告草稿：内存持有（未确认不落盘，避免"未发送的报告"长期滞留）；
- 发送记录：交付结果（收件地址/主题/时间/报告编号），**不落正文**；
- 来信记录：append-only JSONL（`data/private/inbox.jsonl`，gitignored），正文已截断。
"""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class MailStoreError(ValueError):
    pass


class InboxStore:
    """来信台账：append-only，可审计；同一 uid 不重复入库。"""

    def __init__(self, path: str | None = None):
        raw = path or os.environ.get("INBOX_DB_PATH", "")
        self._path = Path(raw) if raw else Path("data/private/inbox.jsonl")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def _read_all(self) -> list[dict[str, Any]]:
        try:
            text = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        out: list[dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def known_uids(self) -> set[str]:
        return {str(r.get("uid")) for r in self._read_all() if r.get("uid")}

    def record(self, mail: dict[str, Any]) -> dict[str, Any]:
        """写入一封来信；缺 uid 或重复 uid 则拒绝/跳过。"""
        uid = str(mail.get("uid") or "").strip()
        if not uid:
            raise MailStoreError("来信缺少 uid")
        with self._lock:
            if uid in {str(r.get("uid")) for r in self._read_all()}:
                return {"recorded": False, "reason": "duplicate uid"}
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(mail, ensure_ascii=False) + "\n")
        return {"recorded": True, "uid": uid}

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._read_all()[-limit:]

    def by_ticket(self, ticket: str) -> list[dict[str, Any]]:
        return [r for r in self._read_all() if r.get("ticket") == ticket]

    def count(self) -> int:
        return len(self._read_all())


class ReportRegistry:
    """报告草稿与发送记录（内存，进程级）。

    草稿只存内存：用户未确认即不落盘，避免"未发送的报告"长期滞留。
    """

    def __init__(self) -> None:
        self._drafts: dict[str, dict[str, Any]] = {}
        self._sent: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def put_draft(self, draft: dict[str, Any]) -> dict[str, Any]:
        rid = str(draft.get("report_id") or "").strip()
        if not rid:
            raise MailStoreError("报告缺少 report_id")
        with self._lock:
            self._drafts[rid] = dict(draft)
        return self._drafts[rid]

    def get_draft(self, report_id: str) -> dict[str, Any] | None:
        with self._lock:
            draft = self._drafts.get(report_id)
        return dict(draft) if draft else None

    def mark_sent(self, report_id: str, delivery: dict[str, Any]) -> dict[str, Any]:
        record = {
            "report_id": report_id,
            "to": delivery.get("to", ""),
            "subject": delivery.get("subject", ""),
            "sent_at": delivery.get("sent_at") or datetime.now(UTC).isoformat(),
            "message_id": delivery.get("message_id", ""),
        }
        with self._lock:
            self._sent[report_id] = record
        return record

    def sent_records(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(v) for v in self._sent.values()]

    def is_sent(self, report_id: str) -> bool:
        with self._lock:
            return report_id in self._sent
