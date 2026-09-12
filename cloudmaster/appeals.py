"""申诉与投诉举报受理（《办法》第 21 条；TC-PRIV-006 / TC-RES-002）。

落地为本地 append-only JSONL（`data/private/`，gitignored，不落业务日志原文），
仅记录申诉所需的最小字段；不含姓名/联系方式（隐私最小化，红线：不索取真实身份）。
"""

from __future__ import annotations

import json
import os
import secrets
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

APPEAL_KINDS = {
    "minor_misjudged": "未成年人模式误判申诉",
    "content": "内容与回复问题投诉",
    "privacy": "隐私与数据使用投诉",
    "other": "其他投诉与举报",
}


class AppealError(ValueError):
    pass


class AppealStore:
    """append-only 申诉受理台账；可审计、可闭环。"""

    def __init__(self, path: str | None = None):
        raw = path or os.environ.get("APPEAL_DB_PATH", "")
        self._path = Path(raw) if raw else Path("data/private/appeals.jsonl")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

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
            "submitted_at": datetime.now(UTC).isoformat(),
            "kind": kind,
            "kind_label": APPEAL_KINDS[kind],
            "text": body[:2000],
            "profile_key": profile_key,
            "status": "received",
        }
        with self._lock:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def count(self) -> int:
        with self._lock:
            try:
                return sum(1 for line in self._path.read_text(encoding="utf-8").splitlines() if line.strip())
            except FileNotFoundError:
                return 0
