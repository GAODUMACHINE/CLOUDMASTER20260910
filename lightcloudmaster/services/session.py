"""会话轮次服务（v0.2.0 ADR-002 / v2.0.0 P4 迁入 services）：读取最小画像注入
user_profile（图内只读），驱动持久化图与最小画像。

v2.0.0 P4（ADR-011 §1 薄壳策略）：实现自 lightcloudmaster/service.py 逐字迁入，
service.py 保留同名再导出不破既有 import（web_app 与既有用例的
`from lightcloudmaster import service` / `service_turn` 继续可用）。
轮次语义修复（agent_hops 每轮重置、跨天时长污染、依赖披露非阻断）已在 P2
落于 time_guard / graph 节点完成，本次迁移为纯搬家、不改行为。

红线：本模块不碰盘、不开文件（画像读写经 store DAL）；user_profile 进图后只读。
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage

# 注解用 storage 版 ProfileStore（v2.0.0 唯一存储底座，ADR-012）；旧 profile_store
# 同形共存至 P3 删除，运行时按鸭子类型兼容（测试注入 fake store 不受影响）。
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
