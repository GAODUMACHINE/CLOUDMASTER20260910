"""LLM 工厂（生产：Qwen3.5-Flash OpenAI 兼容）。测试一律注入 fake_chat_models，禁止触网。
CM_STUB=1 时提供本地确定性替身 StubLLM（不触网、零额度），用于在未开通真实模型前跑通全流程。"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from .config import settings


def create_llm() -> BaseChatModel:
    """构造生产 LLM。密钥/base_url 全部来自环境注入，代码不硬编码。"""
    if not settings.configured():
        raise RuntimeError("生产模型未配置：请提供 QWEN_API_KEY 与 QWEN_API_HOST/.env。测试请注入 fake LLM。")
    return ChatOpenAI(
        model=settings.qwen_model,
        api_key=settings.qwen_api_key,
        base_url=settings.resolved_base_url,
        temperature=0.3,
    )


class _StubReply:
    """最小为鸭子对象：仅需 .content，符合图内 llm.invoke(...) -> obj.content 的用法。"""

    def __init__(self, content: str) -> None:
        self.content = content


class StubLLM:
    """无真实模型/未开通额度时的确定性替身（CM_STUB=1）：不触网、零额度。

    用途：先在本地把「注册→聊天→危机→人工审核」全流程跑通；开通真实模型后切回 create_llm。
    仅返回确定文案，不含诊断/处方/评判，符合禁区。
    """

    def invoke(self, message: object, *args: object, **kwargs: object) -> _StubReply:
        prompt = message.content if hasattr(message, "content") else str(message)
        return _StubReply(self._decide(prompt))

    def _decide(self, prompt: str) -> str:
        # 危机复核 prompt（CONFIRM_PROMPT，含"危机识别复核"）→ 常规话术返回 SAFE，避免误升级
        if "危机识别复核" in prompt:
            return "SAFE"
        # 普通陪伴（REACT_PROMPT 内含「用户的话：…」）→ 确定性支持性回复
        text = prompt.split("用户的话：", 1)[-1].strip()
        base = "我在这里陪着你。听起来你有些低落或压力——先深呼吸，我们慢慢说。"
        if not text:
            return base
        return "收到。你刚才在说" + text[:24] + "……我听见了，先陪你把此刻的感受说说。"


def create_stub_llm() -> StubLLM:
    """构造本地确定性替身（不触网、零额度），供 CM_STUB=1 时使用。"""
    return StubLLM()
