"""单 Agent ReAct（unit）：直接作答 / 工具序列 / 步数上限兜底，全 fake LLM。"""

from __future__ import annotations

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from cloudmaster.react import FALLBACK_ANSWER, MAX_STEPS, react_agent


def _llm(responses: list[str]):
    return GenericFakeChatModel(messages=iter([AIMessage(r) for r in responses]))


def test_direct_answer_with_no_tools():
    out = react_agent(_llm(["你可以试着做几次深呼吸。"]), "我有点紧张")
    assert out == "你可以试着做几次深呼吸。"


def test_tool_call_then_final_answer():
    tools = {"ground": lambda a: f"已落地：{a}（仅供参考，不计入诊断）"}
    out = react_agent(
        _llm(["TOOL:ground:睡前放松", "建议睡前做一次放松练习。"]),
        "焦虑睡不着",
        tools=tools,
    )
    assert "建议睡前做一次放松练习。" in out
    assert "已落地" not in out  # 观察不进最终答案


def test_unknown_tool_observed_then_answer():
    out = react_agent(_llm(["TOOL:no_such:1", "我不清楚，抱歉。"]), "随便", tools={})
    assert out == "我不清楚，抱歉。"


def test_max_steps_falls_back():
    out = react_agent(_llm(["TOOL:loop:1"] * MAX_STEPS), "反复请求", tools={})
    assert out == FALLBACK_ANSWER
