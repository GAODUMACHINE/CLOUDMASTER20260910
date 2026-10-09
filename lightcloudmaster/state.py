"""AgentState（LangGraph TypedDict）：全系统的字段契约。

写入约束：next_agent/turn_count/agent_hops 仅 supervisor 可写，risk_level 仅 crisis，
audit_log/contact_log/next_followup 仅 human_review，usage_meta/turn_notices 仅 time_guard。
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
    # 当轮非阻断通知（time_guard 唯一写）：[{kind: disclosure|reminder|limit_close, text}]
    turn_notices: list[dict[str, Any]]
    review_decision: str  # pending / approve / block
    audit_log: Annotated[list[dict[str, Any]], operator.add]
    contact_log: Annotated[list[dict[str, Any]], operator.add]
    next_followup: dict[str, Any] | None
