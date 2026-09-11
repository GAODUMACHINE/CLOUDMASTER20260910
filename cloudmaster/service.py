"""服务层（v0.2.0，ADR-002）：服务层注入 user_profile（图内只读），驱动持久化图与最小画像。"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage

from .profile_store import ProfileStore


def service_turn(
    graph: Any,
    store: ProfileStore,
    profile_key: str,
    user_text: str,
    config: dict[str, Any],
    extra_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """读取最小画像注入 user_profile（图内只读）；extra_profile 更新画像（白名单校验）。"""
    profile = store.get(profile_key) or {}
    if extra_profile:
        merged = {**profile, **extra_profile}
        store.put(profile_key, merged)
        profile = store.get(profile_key)
    return graph.invoke(
        {"messages": [HumanMessage(user_text)], "user_profile": profile or {}},
        config,
    )
