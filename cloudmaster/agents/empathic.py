"""empathic 节点——支持性陪伴回复。prompt 禁区：不诊断/不开药/不评判。"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

EMPATHIC_PROMPT = (
    "你是一名面向18-25岁青年的心理陪伴助手。只做支持性陪伴、情绪疏导与心理科普，"
    "绝不给出诊断结论、用药建议，也不评判用户。请围绕用户当前表达共情、安抚并给一小节可执行建议。"
    "用户的话：{text}"
)
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
    reply = llm.invoke(EMPATHIC_PROMPT.format(text=text))
    content = str(getattr(reply, "content", ""))
    if risk == "low":
        content = content + LOW_RISK_TAIL
    return {"messages": [AIMessage(content)]}
