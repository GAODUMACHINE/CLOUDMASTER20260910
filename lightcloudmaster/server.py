"""生产入口：本机运行（真实 LLM + 持久化 + 邮件收发 + Web 托管，云朵玻璃前端位于 /web）。

密钥/主机/模型/邮箱凭据全部经 .env 或环境注入（gitignored，绝不硬编码入库）。
测试请勿导入本模块（会在导入时构造真实 LLM/邮件通道）；测试一律注入 fake。
"""

from __future__ import annotations

from .config import settings
from .graph import build_graph
from .inbox import ImapInbox
from .mailer import Mailer, SmtpChannel
from .model import create_llm, create_stub_llm
from .persistence import build_checkpointer
from .profile_store import ProfileStore
from .web_app import create_app


def build_mailer() -> Mailer:
    """按 `.env` 的 SMTP_* 组装发信通道。

    未配置（缺 host/user/password）→ 返回**无通道** Mailer：接口会如实提示「通道未配置」，
    绝不静默假装发送成功。配置齐全 → 真实 SmtpChannel（ssl/starttls/plain）。
    """
    if not settings.smtp_ready:
        return Mailer(None, from_addr=settings.sender, from_name=settings.mail_from_name)
    channel = SmtpChannel(
        host=settings.smtp_host,
        port=settings.smtp_port,
        user=settings.smtp_user,
        password=settings.smtp_password,
        security=settings.smtp_security,
    )
    return Mailer(channel, from_addr=settings.sender, from_name=settings.mail_from_name)


def build_inbox() -> ImapInbox | None:
    """按 `.env` 的 IMAP_* 组装收件通道；未配置返回 None（/api/inbox/poll 返回 503）。"""
    if not settings.imap_ready:
        return None
    return ImapInbox(
        host=settings.imap_host,
        port=settings.imap_port,
        user=settings.imap_user,
        password=settings.imap_password,
        folder=settings.imap_folder,
    )


def build_app():
    """组装完整应用：图 + 持久化 checkpointer/store + 邮件收发 + Web。

    模型选择：settings.cm_stub（CM_STUB=1）→ 本地确定性 StubLLM（零额度/不触网，先跑通全流程）；
    否则 → 真实 Qwen（需该模型已由工作空间对当前 key 授权）。
    审核台令牌经 CM_REVIEWER_TOKEN 注入；为空则审核台一律 403（默认不开放，最小暴露）。"""
    llm = create_stub_llm() if settings.cm_stub else create_llm()
    graph = build_graph(llm, checkpointer=build_checkpointer())
    store = ProfileStore()
    return create_app(
        graph,
        store,
        build_mailer(),
        reviewer_token=settings.cm_reviewer_token,
        inbox=build_inbox(),
    )


app = build_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("lightcloudmaster.server:app", host="127.0.0.1", port=8000, reload=False)
