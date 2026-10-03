"""隐私薄壳（v2.0.0 P3，ADR-011 §1）：PrivacyStore 实现已迁 storage/privacy.py
（统一 SQLite 底座，ADR-012），本模块保留同名再导出——既有
`from lightcloudmaster.privacy import PrivacyStore, ...` 不破。

export_bundle 是与存储无关的纯函数，按 P1 取舍留在原位（不随迁 storage）。
历史：v1.2.0 起（计划书 3.2.4 / 3.1.3 第 6 条）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .storage.privacy import (
    DEFAULT_RETENTION_DAYS,
    RETENTION_CHOICES,
    PrivacyError,
    PrivacyStore,
)

__all__ = [
    "DEFAULT_RETENTION_DAYS",
    "RETENTION_CHOICES",
    "PrivacyError",
    "PrivacyStore",
    "export_bundle",
]


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
