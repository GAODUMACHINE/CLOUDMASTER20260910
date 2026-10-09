"""empathic 节点：共情对话主力输出。prompt 禁区：不诊断/不开药/不评判。"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

from ..react import react_agent

LOW_RISK_TAIL = (
    "\n\n（若情绪持续加重或出现伤害自己的念头，请及时联系可信任的人，或使用审核台提供的紧急资源。）"
)
HIGH_RISK_SUPPORT = (
    "我在这里陪着你。此刻最要紧的是先保证你的安全——请跟着深呼吸，慢慢来。"
    "（L2 危机已转交人工审核：由审核台补充官方已审核的援助热线/紧急联系人资源后再发送。）"
)


def _last_user_text(state: dict[str, Any]) -> str:
    for m in reversed(state.get("messages") or []):
        if getattr(m, "type", "") == "human":
            return str(m.content)
    return ""


def empathic_node(state: dict[str, Any], llm: Any) -> dict[str, Any]:
    risk = state.get("risk_level", "none")
    text = _last_user_text(state)
    if risk == "high":
        return {"messages": [AIMessage(HIGH_RISK_SUPPORT)]}
    profile = state.get("user_profile") or {}
    age = profile.get("age")
    minor_mode = isinstance(age, int) and age < 18
    # 未成年走收紧模板（简短温和、不展开敏感细节、安全优先引导线下成年人）。
    content = react_agent(llm, text, minor_mode=minor_mode)
    if risk == "low":
        content = content + LOW_RISK_TAIL
    return {"messages": [AIMessage(content)]}
