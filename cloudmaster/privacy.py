"""隐私与数据保留（计划书 3.2.4 数据设计与隐私保护 / 3.1.3 第 6 条隐私开关）。

补齐缺失能力：
- 会话保留期可选 7/30/90 天（§3.2.4「保留期 7/30/90 天可配」）；
- 一键导出（消息原文由调用方从 Checkpointer 取出后传入，本模块不落原文）；
- 到期删除计划（到期即删，可审计）。

红线：导出内容只回传给本人；保留期设置只存匿名标识，不存任何联系方式。
"""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

RETENTION_CHOICES = (7, 30, 90)
DEFAULT_RETENTION_DAYS = 30


class PrivacyError(ValueError):
    pass


class PrivacyStore:
    """保留期偏好（含创建时间），文件后备 JSON，`data/private/`，gitignored。"""

    def __init__(self, path: str | None = None):
        raw = path or os.environ.get("PRIVACY_DB_PATH", "")
        self._path = Path(raw) if raw else Path("data/private/privacy.json")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        try:
            self._data = json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            self._data = {}

    def _save(self) -> None:
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._path)

    def set_retention(self, key: str, days: int, *, now: datetime | None = None) -> dict[str, Any]:
        if days not in RETENTION_CHOICES:
            raise PrivacyError(f"保留期只支持 {list(RETENTION_CHOICES)} 天")
        moment = now or datetime.now(UTC)
        with self._lock:
            prev = self._data.get(key) or {}
            record = {
                "retention_days": days,
                "created_at": prev.get("created_at") or moment.isoformat(),
                "updated_at": moment.isoformat(),
            }
            self._data[key] = record
            self._save()
        return record

    def get_retention(self, key: str) -> dict[str, Any]:
        """未设置时返回默认 30 天，不落盘（惰性默认）。"""
        with self._lock:
            record = self._data.get(key)
        if record is None:
            return {"retention_days": DEFAULT_RETENTION_DAYS, "created_at": None, "updated_at": None}
        return dict(record)

    def purge_schedule(self, key: str, *, now: datetime | None = None) -> dict[str, Any]:
        """到期删除计划：created_at + retention_days。"""
        moment = now or datetime.now(UTC)
        record = self.get_retention(key)
        created_raw = record.get("created_at")
        days = record["retention_days"]
        if not created_raw:
            return {
                "retention_days": days,
                "delete_after": None,
                "expired": False,
                "note": "尚无会话创建时间记录，删除计划自首次会话起算。",
            }
        try:
            created = datetime.fromisoformat(created_raw)
        except ValueError:
            created = moment
        delete_after = created + timedelta(days=days)
        return {
            "retention_days": days,
            "delete_after": delete_after.isoformat(),
            "expired": moment >= delete_after,
            "note": "到期后会话数据将被删除。",
        }

    def forget(self, key: str) -> bool:
        with self._lock:
            existed = key in self._data
            if existed:
                del self._data[key]
                self._save()
            return existed


def export_bundle(
    *,
    profile_key: str,
    profile: dict[str, Any] | None,
    messages: list[Any] | None,
    retention: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """一键导出：最小画像 + 会话消息 + 保留期。原文只回传本人，服务端不额外落盘。"""
    moment = now or datetime.now(UTC)
    items: list[dict[str, str]] = []
    for m in messages or []:
        role = "user" if getattr(m, "type", "") == "human" else "ai"
        items.append({"role": role, "text": str(getattr(m, "content", ""))})
    return {
        "exported_at": moment.isoformat(),
        "profile_key": profile_key,
        "profile": dict(profile or {}),
        "retention": retention or {},
        "message_count": len(items),
        "messages": items,
        "note": "导出内容仅含你的匿名最小画像与会话记录，不含姓名/联系方式。",
    }
