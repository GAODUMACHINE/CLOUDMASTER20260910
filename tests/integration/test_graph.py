"""集成：fake LLM 走完整图（守卫顺序 + L2 中断恢复），禁止触网。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from lightcloudmaster.graph import build_graph

T0 = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


def _config(tid: str) -> dict:
    return {"configurable": {"thread_id": tid}}


def test_normal_flow_reaches_empathic(fake_llm_empathic):
    graph = build_graph(fake_llm_empathic, checkpointer=InMemorySaver())
    res = graph.invoke(
        {"messages": [HumanMessage("我今天有点累")], "user_profile": {"age": 22}},
        _config("c1"),
    )
    assert res["risk_level"] == "none"
    assert res["next_agent"] == "empathic"
    assert isinstance(res["messages"][-1], AIMessage)


def test_knowledge_keyword_routes_to_knowledge(fake_llm_empathic):
    graph = build_graph(fake_llm_empathic, checkpointer=InMemorySaver())
    res = graph.invoke(
        {"messages": [HumanMessage("失眠是怎么回事，科普一下")], "user_profile": {"age": 22}},
        _config("c2"),
    )
    assert res["next_agent"] == "knowledge"
    assert isinstance(res["messages"][-1], AIMessage)


def test_l2_interrupt_and_resume(fake_llm_crisis_danger):
    graph = build_graph(fake_llm_crisis_danger, checkpointer=InMemorySaver())
    cfg = _config("c3")
    graph.invoke(
        {"messages": [HumanMessage("我想自杀活不下去")], "user_profile": {"age": 22}},
        cfg,
    )
    state = graph.get_state(cfg)
    assert state.next == ("human_review",)
    graph.invoke(Command(resume="ok", update={"review_decision": "approve"}), cfg)
    final = graph.get_state(cfg)
    assert final.values["review_decision"] == "approve"
    assert final.values["risk_level"] == "high"


def _now_fn():
    return T0 + timedelta(minutes=61)


def test_time_guard_minor_close_short_circuits(fake_llm_empathic):
    graph = build_graph(fake_llm_empathic, now_fn=_now_fn, checkpointer=InMemorySaver())
    res = graph.invoke(
        {
            "messages": [HumanMessage("可以聊一会吗")],
            "user_profile": {"age": 16},
            "usage_meta": {"session_started_at": T0.isoformat()},
        },
        _config("c4"),
    )
    assert res["usage_meta"]["fired"] is True
    assert res.get("risk_level") is None
    assert res.get("next_agent") in (None, "")
