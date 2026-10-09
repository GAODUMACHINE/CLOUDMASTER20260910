"""运行时配置（Qwen OpenAI 兼容），全部经环境变量/.env 注入，禁止硬编码密钥或绝对路径。"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    qwen_api_key: str = ""
    qwen_api_host: str = ""
    # 生产默认 qwen-flash：首 token P50≈0.3s。qwen3.5-flash 为思考模型（首 token≈14s），
    # 仅在明确需要推理质量时手动切换。
    qwen_model: str = "qwen-flash"
    qwen_base_url: str = ""
    # CM_STUB=1 -> 本地确定性替身模型（零额度/不触网），用于演示与本地演练
    cm_stub: bool = False
    # 审核台访问令牌：为空则审核台一律 403（默认不开放）
    cm_reviewer_token: str = ""

    # ---- 邮件：全部经环境变量/.env 注入；为空则对应通道如实关闭 ----
    # 发信（SMTP）：发送疏导报告与人工联络
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""  # 缺省回退到 smtp_user
    smtp_security: str = "ssl"  # ssl / starttls / plain（plain 仅本地调试）
    # 收信（IMAP）：接收回信/退信/退订
    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""
    imap_folder: str = "INBOX"
    mail_from_name: str = "LightCloudMaster 拾光云上"

    @property
    def smtp_ready(self) -> bool:
        """是否具备真实发信条件。缺任一必填项即视为未配置（通道关闭，不静默失败）。"""
        return bool(self.smtp_host.strip() and self.smtp_user.strip() and self.smtp_password)

    @property
    def imap_ready(self) -> bool:
        return bool(self.imap_host.strip() and self.imap_user.strip() and self.imap_password)

    @property
    def sender(self) -> str:
        return self.smtp_from.strip() or self.smtp_user.strip()

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
