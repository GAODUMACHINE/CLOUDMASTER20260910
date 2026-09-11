"""集成（v0.2.0 会话记忆）：文件 Checkpointer 跨实例接续 + 最小画像注入，全 fake LLM。"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from cloudmaster.graph import build_graph
from cloudmaster.persistence import build_checkpointer
from cloudmaster.profile_store import ProfileStore
from cloudmaster.service import service_turn


def _cfg(tid):
    return {"configurable": {"thread_id": tid}}


def test_turn_count_increments_across_invocations(fake_llm_empathic):
    graph = build_graph(fake_llm_empathic, checkpointer=InMemorySaver())
    r1 = graph.invoke({"messages": [HumanMessage("第一轮")], "user_profile": {"age": 22}}, _cfg("t1"))
    assert r1["turn_count"] == 1
    r2 = graph.invoke({"messages": [HumanMessage("第二轮")], "user_profile": {"age": 22}}, _cfg("t1"))
    assert r2["turn_count"] == 2


def test_new_thread_resets_turn(fake_llm_empathic):
    graph = build_graph(fake_llm_empathic, checkpointer=InMemorySaver())
    graph.invoke({"messages": [HumanMessage("a")], "user_profile": {"age": 22}}, _cfg("ta"))
    r = graph.invoke({"messages": [HumanMessage("b")], "user_profile": {"age": 22}}, _cfg("tb"))
    assert r["turn_count"] == 1


def test_checkpoint_durability_across_instances(fake_llm_empathic, tmp_path):
    db = tmp_path / "mem.sqlite3"
    g1 = build_graph(fake_llm_empathic, checkpointer=build_checkpointer(str(db)))
    cfg = _cfg("u1")
    g1.invoke({"messages": [HumanMessage("第一次")], "user_profile": {"age": 22}}, cfg)
    g2 = build_graph(fake_llm_empathic, checkpointer=build_checkpointer(str(db)))
    r2 = g2.invoke({"messages": [HumanMessage("次日继续")], "user_profile": {"age": 22}}, cfg)
    assert r2["turn_count"] == 2
    assert isinstance(r2["messages"][-1], AIMessage)


def test_service_injects_profile(tmp_path, fake_llm_empathic):
    store = ProfileStore(str(tmp_path / "p.json"))
    store.put("u9", {"age": 22})
    graph = build_graph(fake_llm_empathic, checkpointer=InMemorySaver())
    res = service_turn(graph, store, "u9", "你好", _cfg("svc1"))
    assert res["user_profile"] == {"age": 22}
    assert res["turn_count"] == 1


def test_service_updates_profile_whitelisted(tmp_path, fake_llm_empathic):
    store = ProfileStore(str(tmp_path / "p2.json"))
    graph = build_graph(fake_llm_empathic, checkpointer=InMemorySaver())
    service_turn(graph, store, "u10", "hi", _cfg("svc2"), extra_profile={"age": 20})
    assert store.get("u10") == {"age": 20}
