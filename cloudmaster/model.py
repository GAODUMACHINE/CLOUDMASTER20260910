"""LLM 工厂（生产：Qwen3.5-Flash OpenAI 兼容）。测试一律注入 fake_chat_models，禁止触网。"""

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
