"""AgentState（LangGraph TypedDict）——字段 schema 必须先经 ADR-001 评审。

写入权限表（ADR-001）：
  messages      各对话节点(add_messages)
  risk_level    仅 crisis
  next_agent    仅 supervisor
  citations     仅 knowledge(operator.add，只增不删)
  turn_count    仅 supervisor
  user_profile  服务层注入，图内只读
  usage_meta    仅 time_guard
  crisis_basis  仅 crisis
  agent_hops    仅 supervisor
  review_decision 仅 human_review
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
