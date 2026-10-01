"""已审核转介资源（TC-RES-001）。

红线：**不硬编码任何真实热线号码**。默认返回空列表；只有经人工审核后台录入
（须令牌 + 审核人署名）的号码才会下发给前端。未审核号码一律不下发。
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RESOURCE_KINDS = {
    "school": "学校心理健康教育与咨询中心",
    "hospital": "医院心理科/精神卫生中心",
    "hotline": "心理援助热线",
    "emergency": "紧急救助",
    "other": "其他转介资源",
}

# 宽松格式校验：允许数字、空格、连字符、括号与可选区号；拒绝一切非号码字符。
_TEL_RE = re.compile(r"^[0-9][0-9\-\s()]{2,24}$")


class ResourceError(ValueError):
    pass


class ResourceStore:
    """人工审核后的转介资源台账（JSONL，`data/private/`，gitignored）。"""

    def __init__(self, path: str | None = None):
        raw = path or os.environ.get("RESOURCE_DB_PATH", "")
        self._path = Path(raw) if raw else Path("data/private/resources.jsonl")
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

    def add(
        self,
        *,
        title: str,
        detail: str = "",
        kind: str = "school",
        tel: str = "",
        reviewer: str = "",
    ) -> dict[str, Any]:
        """录入一条已审核资源。title 与 reviewer 必填（无审核人签名不许下发）。"""
        name = (title or "").strip()
        if not name:
            raise ResourceError("资源名称不能为空")
        if not (reviewer or "").strip():
            raise ResourceError("必须记录审核人署名（未经人工审核的资源不下发）")
        if kind not in RESOURCE_KINDS:
            raise ResourceError(f"不支持的资源类型: {kind}")
        number = (tel or "").strip()
        if number and not _TEL_RE.match(number):
            raise ResourceError("号码格式不合法")
        record = {
            "title": name,
            "detail": (detail or "").strip()[:300],
            "kind": kind,
            "kind_label": RESOURCE_KINDS[kind],
            "tel": number,
            "reviewer": reviewer.strip(),
            "approved_at": datetime.now(UTC).isoformat(),
        }
        with self._lock:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def approved(self) -> list[dict[str, Any]]:
        """已审核资源（默认空：未录入任何号码即不下发任何号码）。"""
        return [r for r in self._read_all() if r.get("title") and r.get("reviewer")]
