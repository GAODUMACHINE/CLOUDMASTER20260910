"""supervisor 节点——仅此处可写 next_agent / turn_count / agent_hops（ADR-001）。"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

MAX_AGENT_HOPS = 3
KNOWLEDGE_KEYWORDS = ["知识", "科普", "怎么回事", "原理", "科普一下", "是怎么回事"]


def _last_user_text(state: dict[str, Any]) -> str:
    for m in reversed(state.get("messages") or []):
        if getattr(m, "type", "") == "human":
            return str(m.content)
    return ""


def decide_next(state: dict[str, Any]) -> str:
    risk = state.get("risk_level", "none")
    text = _last_user_text(state)
    has_knowledge = any(k in text for k in KNOWLEDGE_KEYWORDS)
    if risk == "high":
        return "empathic"  # L2 由 human_review 处理后回到这里交付支持性回应
    if has_knowledge and risk in ("none", "low"):
        return "knowledge"
    return "empathic"


def supervisor_node(state: dict[str, Any], llm: Any | None = None) -> dict[str, Any]:
    hops = int(state.get("agent_hops") or 0)
    next_hops = hops + 1
    turn = int(state.get("turn_count") or 0) + 1
    if next_hops > MAX_AGENT_HOPS:
        logger.warning("agent_hops=%s 超过上限 %s，强制 next_agent=end 防死循环", next_hops, MAX_AGENT_HOPS)
        return {"next_agent": "end", "agent_hops": next_hops, "turn_count": turn}
    return {"next_agent": decide_next(state), "agent_hops": next_hops, "turn_count": turn}
