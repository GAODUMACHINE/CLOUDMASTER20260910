"""AgentState（LangGraph TypedDict）——schema 须经 ADR 评审。
- ADR-001：基础字段 + 守卫顺序
- ADR-003：audit_log / contact_log / next_followup（human_review 唯一写）
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    risk_level: str
    next_agent: str
    citations: Annotated[list[dict[str, Any]], operator.add]
    turn_count: int
    user_profile: dict[str, Any]
    usage_meta: dict[str, Any]
    crisis_basis: dict[str, Any]
    agent_hops: int
    review_decision: str  # pending / approve / block
    audit_log: Annotated[list[dict[str, Any]], operator.add]
    contact_log: Annotated[list[dict[str, Any]], operator.add]
    next_followup: dict[str, Any] | None
