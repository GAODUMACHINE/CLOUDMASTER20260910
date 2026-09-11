"""运行时配置（Qwen OpenAI 兼容），全部经环境变量/.env 注入，禁止硬编码密钥或绝对路径。"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    qwen_api_key: str = ""
    qwen_api_host: str = ""
    qwen_model: str = "qwen3.5-flash"
    qwen_base_url: str = ""
    # CM_STUB=1 -> 用本地确定性 stub 模型跑通全流程（零额度/不触网），真实模型开通后再取消
    cm_stub: bool = False

    @property
    def resolved_base_url(self) -> str:
        """OpenAI 兼容 base_url；可被 QWEN_BASE_URL 覆盖，否则按阿里云 MaaS /compatible-mode/v1 推断。"""
        if self.qwen_base_url.strip():
            return self.qwen_base_url.strip().rstrip("/")
        host = self.qwen_api_host.strip().rstrip("/")
        if not host:
            return ""
        return f"https://{host}/compatible-mode/v1"

    def configured(self) -> bool:
        """是否已具备调用生产模型所需的最小配置。测试环境允许为空。"""
        return bool(self.qwen_api_key.strip() and self.resolved_base_url)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
