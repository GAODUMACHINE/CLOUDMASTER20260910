"""knowledge 节点——心理科普（v0.1.0 占位，RAG/引用在 v0.4.0 接入）。仅此处可写 citations。"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

KNOWLEDGE_PROMPT = (
    "面向18-25岁青年的心理科普：就用户问题给一小节科学、不诊断、不开药、不评判的科普内容，并附来源说明。"
    "用户问题：{text}"
)


def _last_user_text(state: dict[str, Any]) -> str:
    for m in reversed(state.get("messages") or []):
        if getattr(m, "type", "") == "human":
            return str(m.content)
    return ""


def knowledge_node(state: dict[str, Any], llm: Any) -> dict[str, Any]:
    text = _last_user_text(state)
    reply = llm.invoke(KNOWLEDGE_PROMPT.format(text=text))
    content = str(getattr(reply, "content", ""))
    update: dict[str, Any] = {"messages": [AIMessage(content)]}
    return update
