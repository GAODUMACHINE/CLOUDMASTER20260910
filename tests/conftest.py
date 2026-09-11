"""共享 fixtures：一律 fake LLM（无限循环，不耗尽），禁止触网/真实模型。"""

from __future__ import annotations

import itertools

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage


def _model(responses):
    return GenericFakeChatModel(messages=itertools.cycle([AIMessage(r) for r in responses]))


@pytest.fixture
def fake_llm_empathic():
    return _model(["我理解你的感受，这里有一些可以放松的小方法。"])


@pytest.fixture
def fake_llm_crisis_danger():
    return _model(["DANGER", "我在这里陪着你。"])


@pytest.fixture
def fake_llm_crisis_safe_downgrade():
    return _model(["SAFE", "我理解你的感受。"])
