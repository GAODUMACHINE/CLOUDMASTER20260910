"""RAG 检索契约（unit，ADR-004）：库内命中 / 库外为空。"""

from __future__ import annotations

from cloudmaster.rag.stub import StubRetriever


def test_retrieves_in_corpus():
    hits = StubRetriever().retrieve("焦虑怎么缓解")
    assert hits
    assert all("虚构" in d.source for d in hits)


def test_out_of_corpus_empty():
    assert StubRetriever().retrieve("如何解答量子物理题") == []
