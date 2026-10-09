"""会话轮次服务：读取最小画像注入 user_profile（图内只读），驱动持久化图。

红线：本模块不碰盘、不开文件（画像读写经 store DAL）。
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage

from ..storage.profiles import ProfileStore


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
