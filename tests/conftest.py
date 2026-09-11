"""共享 fixtures：一律 fake LLM，禁止触网/真实模型。"""

from __future__ import annotations

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage


def _model(responses: list[str]) -> BaseChatModel:
    return GenericFakeChatModel(messages=iter([AIMessage(r) for r in responses]))


@pytest.fixture
def fake_llm_empathic() -> BaseChatModel:
    """正常回应路径（crisis 无规则命中 -> 不触发 LLM；empathic 返回一句支持文案）。"""
    return _model(["我理解你的感受，这里有一些可以放松的小方法。"])


@pytest.fixture
def fake_llm_crisis_danger() -> BaseChatModel:
    """LLM 复核维持 DANGER（用于 L1/L2 降误报保持）。"""
    return _model(["DANGER", "我在这里陪着你。"])


@pytest.fixture
def fake_llm_crisis_safe_downgrade() -> BaseChatModel:
    """rule=L1/L2 时 LLM 复核 SAFE 触发降级；随后 empathic 的正常回应。"""
    return _model(["SAFE", "我理解你的感受。"])
