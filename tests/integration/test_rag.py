"""集成（v0.4.0）：knowledge RAG 引用必附 + 库外边界（fake LLM）。"""

from __future__ import annotations

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from cloudmaster.graph import build_graph


def _cfg(tid):
    return {"configurable": {"thread_id": tid}}


def test_knowledge_in_corpus_attaches_citations(fake_llm_empathic):
    graph = build_graph(fake_llm_empathic, checkpointer=InMemorySaver())
    res = graph.invoke(
        {"messages": [HumanMessage("焦虑怎么缓解，科普一下")], "user_profile": {"age": 22}},
        _cfg("rag1"),
    )
    assert res["next_agent"] == "knowledge"
    assert res["citations"]
    assert "虚构" in res["citations"][0]["source"]
    assert "参考来源" in res["messages"][-1].content


def test_knowledge_out_of_boundary_no_citations(fake_llm_empathic):
    graph = build_graph(fake_llm_empathic, checkpointer=InMemorySaver())
    res = graph.invoke(
        {"messages": [HumanMessage("量子力学是怎么回事")], "user_profile": {"age": 22}},
        _cfg("rag2"),
    )
    assert res["next_agent"] == "knowledge"
    assert res.get("citations") == []
    assert "超出我的心理科普知识边界" in res["messages"][-1].content
