"""集成（v0.3.0）：L2 人工审核 approve/block 全链路（审计+联络桩+回访）。"""

from __future__ import annotations

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from lightcloudmaster.graph import build_graph


def _cfg(tid):
    return {"configurable": {"thread_id": tid}}


def test_l2_approve_full_chain(fake_llm_crisis_danger):
    graph = build_graph(fake_llm_crisis_danger, checkpointer=InMemorySaver())
    cfg = _cfg("r1")
    graph.invoke({"messages": [HumanMessage("我想自杀活不下去")], "user_profile": {"age": 22}}, cfg)
    assert graph.get_state(cfg).next == ("human_review",)
    graph.invoke(Command(resume="ok", update={"review_decision": "approve"}), cfg)
    fin = graph.get_state(cfg)
    assert fin.values["review_decision"] == "approve"
    assert fin.values["audit_log"] and fin.values["contact_log"]
    assert fin.values["next_followup"] is not None


def test_l2_block_no_contact(fake_llm_crisis_danger):
    graph = build_graph(fake_llm_crisis_danger, checkpointer=InMemorySaver())
    cfg = _cfg("r2")
    graph.invoke({"messages": [HumanMessage("我想自杀")], "user_profile": {"age": 21}}, cfg)
    graph.invoke(Command(resume="ok", update={"review_decision": "block"}), cfg)
    fin = graph.get_state(cfg)
    assert fin.values["review_decision"] == "block"
    assert fin.values["audit_log"] and fin.values["contact_log"] == []
    assert fin.values["next_followup"] is None
