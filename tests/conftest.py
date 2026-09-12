"""共享 fixtures：一律 fake LLM（prompt 感知、确定性），禁止触网/真实模型。

fake 按 prompt 类型分流作答，使「规则层 + LLM 层（复核/语义筛查）」两条路径都可离线断言：
- 复核 prompt（CONFIRM_PROMPT）→ confirm 应答
- 语义筛查 prompt（SCREEN_PROMPT）→ screen 应答
- 其余（陪伴/科普）→ answer 应答
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

CONFIRM_MARK = "危机识别复核"
SCREEN_MARK = "语义筛查"


class ScriptedLLM:
    """prompt 感知的确定性 fake ChatModel（仅需 .invoke(...)->.content）。"""

    def __init__(
        self,
        *,
        answer: str = "我理解你的感受，这里有一些可以放松的小方法。",
        confirm: str = "SAFE",
        screen: str = "SAFE",
    ) -> None:
        self._answer = answer
        self._confirm = confirm
        self._screen = screen

    def invoke(self, message: object, *args: object, **kwargs: object) -> AIMessage:
        prompt = getattr(message, "content", None) or str(message)
        if CONFIRM_MARK in prompt:
            return AIMessage(self._confirm)
        if SCREEN_MARK in prompt:
            return AIMessage(self._screen)
        return AIMessage(self._answer)


@pytest.fixture
def fake_llm_empathic():
    return ScriptedLLM()


@pytest.fixture
def fake_llm_crisis_danger():
    """规则命中 L2 → LLM 复核 DANGER（保持 L2）。"""
    return ScriptedLLM(confirm="DANGER", answer="我在这里陪着你。")


@pytest.fixture
def fake_llm_crisis_safe_downgrade():
    """规则命中 L2/L1 → LLM 复核 SAFE（降误报）。"""
    return ScriptedLLM(confirm="SAFE", answer="我理解你的感受。")


@pytest.fixture
def fake_llm_screen_danger():
    """规则未命中 → LLM 语义筛查 DANGER（补漏检：计划安排/告别暗示/隐喻等）。"""
    return ScriptedLLM(screen="DANGER", answer="我在这里陪着你。")


@pytest.fixture
def fake_llm_screen_watch():
    """规则未命中 → LLM 语义筛查 WATCH（判为 low）。"""
    return ScriptedLLM(screen="WATCH", answer="我理解你的感受。")


@pytest.fixture
def fake_llm_danger_both():
    """复核与语义筛查均判 DANGER：验证「规则层或 LLM 层任一层命中即达 L2」。"""
    return ScriptedLLM(confirm="DANGER", screen="DANGER", answer="我在这里陪着你。")
