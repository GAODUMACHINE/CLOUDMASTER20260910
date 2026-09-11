"""StubLLM 回归：CM_STUB=1 时本地确定性替身，不触网、零额度，可跑通全流程。"""

from __future__ import annotations

from cloudmaster.model import StubLLM, _StubReply, create_stub_llm


def test_stub_llm_returns_reply_content():
    llm = create_stub_llm()
    reply = llm.invoke("用户的话：我很焦虑睡不着")
    assert isinstance(reply, _StubReply)
    assert isinstance(reply.content, str) and reply.content.strip()


def test_stub_llm_crisis_confirm_returns_safe():
    # 危机复核 prompt（CONFIRM_PROMPT，含「危机识别复核」）→ 常规话术返回 SAFE，避免误升级
    llm = StubLLM()
    assert llm._decide("你是一名危机识别复核助手。原话：我想死") == "SAFE"


def test_stub_llm_reply_echoes_user_words():
    llm = StubLLM()
    reply = llm.invoke("用户的话：我最近压力很大")
    assert "压力" in reply.content or "收到" in reply.content
