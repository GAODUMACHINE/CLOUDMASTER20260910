"""单 Agent ReAct（unit）：直接作答 / 工具序列 / 步数上限兜底，全 fake LLM。"""

from __future__ import annotations

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from lightcloudmaster.react import FALLBACK_ANSWER, MAX_STEPS, react_agent


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


class _PromptSpy:
    """记录收到的 prompt，并按顺序作答（末条可重复）。"""

    def __init__(self, *answers: str):
        self.answers = list(answers)
        self.prompts: list[str] = []

    def invoke(self, message: object, *args: object, **kwargs: object) -> AIMessage:
        self.prompts.append(str(getattr(message, "content", message)))
        idx = min(len(self.prompts) - 1, len(self.answers) - 1)
        return AIMessage(self.answers[idx])


def test_no_tools_prompt_does_not_advertise_tool_protocol():
    """无工具时不得宣传 TOOL 协议，否则真实模型会空转 max_steps（在线核验发现）。"""
    spy = _PromptSpy("我在，慢慢说。")
    out = react_agent(spy, "我有点紧张")
    assert out == "我在，慢慢说。"
    assert "没有任何可用工具" in spy.prompts[0]
    assert "TOOL:<工具名>" not in spy.prompts[0]


def test_unknown_tool_observation_reminds_no_tools():
    """空工具集下收到 TOOL: 调用时，观察里要明确提示没有可用工具，促使模型直接作答。"""
    spy = _PromptSpy("TOOL:no_such:1", "我们直接聊聊你的感受吧。")
    out = react_agent(spy, "我有点紧张", tools={})
    assert out == "我们直接聊聊你的感受吧。"
    assert len(spy.prompts) == 2
    assert "当前没有可用工具" in spy.prompts[1]
