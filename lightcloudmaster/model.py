"""LLM 工厂：生产用 qwen-flash（OpenAI 兼容协议接 DashScope），CM_STUB=1 时用本地
确定性替身 StubLLM（不触网、零额度）。测试一律注入 fake 模型。"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from .config import settings


def create_llm() -> BaseChatModel:
    """构造生产 LLM，密钥/base_url 全部来自环境注入。

    streaming=True 使 invoke 期间即发 token 回调——web/sse.py 的
    stream_mode="messages" 依赖它逐 token 下发。
    """
    if not settings.configured():
        raise RuntimeError("生产模型未配置：请提供 QWEN_API_KEY 与 QWEN_API_HOST/.env。测试请注入 fake LLM。")
    return ChatOpenAI(
        model=settings.qwen_model,
        api_key=settings.qwen_api_key,
        base_url=settings.resolved_base_url,
        temperature=0.3,
        streaming=True,
    )


class _StubReply:
    """最小鸭子对象：仅需 .content，符合图内 llm.invoke(...) -> obj.content 的用法。"""

    def __init__(self, content: str) -> None:
        self.content = content


class StubLLM:
    """无真实模型/未开通额度时的确定性替身：不触网、零额度。

    仅返回确定文案，不含诊断/处方/评判；用于在本地把
    「注册→聊天→危机→人工审核」全流程跑通。
    """

    def invoke(self, message: object, *args: object, **kwargs: object) -> _StubReply:
        prompt = message.content if hasattr(message, "content") else str(message)
        return _StubReply(self._decide(prompt))

    def _decide(self, prompt: str) -> str:
        # 危机复核维持规则词表级别（回 WATCH 不升不降）：回 SAFE 会把规则级 L2 降级、
        # 断掉 L2 挂起→人工审核链路；回 DANGER 会把全部 L1 词误升 L2。
        if "危机识别复核" in prompt:
            return "WATCH"
        # 语义筛查看作 SAFE：离线替身不承担语义召回，生产中由真实模型承担。
        if "语义筛查" in prompt:
            return "SAFE"
        # 普通陪伴或科普 → 确定性支持性回复
        text = prompt.split("用户的话：", 1)[-1]
        if "用户问题：" in prompt:
            text = prompt.split("用户问题：", 1)[-1]
        text = text.strip()
        base = "我在这里陪着你。听起来你有些低落或压力——先深呼吸，我们慢慢说。"
        if not text:
            return base
        return "收到。你刚才在说" + text[:24] + "……我听见了，先陪你把此刻的感受说说。"


def create_stub_llm() -> StubLLM:
    return StubLLM()
