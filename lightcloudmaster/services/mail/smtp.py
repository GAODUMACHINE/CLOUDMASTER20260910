"""邮件发送：真实 SMTP 通道 + 产品级 HITL 确认。

红线与隐私：
- 未确认（decision != approve）或确认令牌不符，绝不发送，且不产生发送记录；
- 凭据只经环境变量/.env 注入，绝不硬编码入库；
- 发送记录只留收件地址/主题/时间，不落邮件正文。

确认令牌比对用 secrets.compare_digest（常数时间比较，防计时侧信道逐字节猜令牌）。

通道设计：`Mailer(channel=...)` 可注入任意实现了 `send(message)` 的通道。
缺省 channel=None → 不发送（返回 sent=False 并附原因，不会静默假装成功）；
SmtpChannel → 真实 SMTP（ssl / starttls）；测试可注入 RecordingChannel。
"""

from __future__ import annotations

import secrets
import smtplib
import ssl
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Any


class MailError(RuntimeError):
    pass


@dataclass
class OutgoingMail:
    """一封待发邮件（通道收到的最小契约）。"""

    to: str
    subject: str
    body: str
    from_addr: str = ""
    from_name: str = ""
    # 便于收信侧按 ticket 归属回信（写入 Message-ID / 主题前缀）
    ticket: str = ""
    message_id: str = ""

    def to_email_message(self) -> EmailMessage:
        msg = EmailMessage()
        msg["To"] = self.to
        if self.from_addr:
            msg["From"] = formataddr((self.from_name, self.from_addr)) if self.from_name else self.from_addr
        msg["Subject"] = self.subject
        msg["Message-ID"] = self.message_id or make_msgid(domain="lightcloudmaster.local")
        msg["Date"] = datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S +0000")
        # 明文 + UTF-8；不附任何用户对话原文以外的内容
        msg.set_content(self.body, charset="utf-8")
        return msg


class SmtpChannel:
    """真实 SMTP 通道（标准库 smtplib）。

    security: "ssl"（隐式 TLS，默认，465）/ "starttls"（587）/ "plain"（仅本地调试）。
    """

    def __init__(
        self,
        *,
        host: str,
        port: int = 465,
        user: str = "",
        password: str = "",
        security: str = "ssl",
        timeout: float = 15.0,
    ) -> None:
        if security not in ("ssl", "starttls", "plain"):
            raise MailError(f"不支持的 SMTP 安全模式: {security}")
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.security = security
        self.timeout = timeout

    def send(self, message: OutgoingMail) -> dict[str, Any]:
        msg = message.to_email_message()
        context = ssl.create_default_context()
        try:
            if self.security == "ssl":
                server: smtplib.SMTP = smtplib.SMTP_SSL(
                    self.host, self.port, timeout=self.timeout, context=context
                )
            else:
                server = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
            with server:
                if self.security == "starttls":
                    server.starttls(context=context)
                if self.user:
                    server.login(self.user, self.password)
                server.send_message(msg)
        except (OSError, smtplib.SMTPException) as exc:
            # 不吞异常：绝不能让"未送达"被当成成功。
            raise MailError(f"SMTP 发送失败：{exc}") from exc
        return {"sent": True, "message_id": msg["Message-ID"], "channel": self.security}


class RecordingChannel:
    """内存记录通道（测试/干跑）。"""

    def __init__(self) -> None:
        self.messages: list[OutgoingMail] = []

    def send(self, message: OutgoingMail) -> dict[str, Any]:
        self.messages.append(message)
        return {"sent": True, "message_id": message.message_id, "channel": "recording"}


class Mailer:
    def __init__(self, channel: Any = None, *, from_addr: str = "", from_name: str = "") -> None:
        self._channel = channel
        self._from_addr = from_addr
        self._from_name = from_name
        # 发送台账：只留地址/主题/时间，不落正文（隐私最小化）。
        self.sent: list[dict[str, str]] = []
        self.failed: list[dict[str, str]] = []

    @property
    def enabled(self) -> bool:
        """是否具备真实发送能力（未配置通道时为 False，接口据此提示而未启用）。"""
        return self._channel is not None

    def send(self, *, to: str, subject: str, body: str, ticket: str = "") -> dict[str, Any]:
        """实际发送。未配置通道 → 抛 MailError（不静默假装成功）。"""
        if self._channel is None:
            raise MailError("邮件通道未配置（请在 .env 设置 SMTP_* ）")
        message = OutgoingMail(
            to=to,
            subject=subject,
            body=body,
            from_addr=self._from_addr,
            from_name=self._from_name,
            ticket=ticket,
        )
        result = self._channel.send(message)
        record = {
            "to": to,
            "subject": subject,
            "sent_at": datetime.now(UTC).isoformat(),
            "message_id": str(result.get("message_id") or ""),
        }
        self.sent.append(record)
        return {"sent": True, **record}

    def send_if_confirmed(
        self,
        *,
        email: str,
        subject: str,
        body: str,
        decision: str,
        confirm_token: str,
        expected_token: str,
        ticket: str = "",
    ) -> dict[str, Any]:
        """产品级 HITL 闸门：只有「已确认 + 令牌相符」才发送。

        - decision != "approve" → 不发送、**不产生发送记录**（用户拒绝不留痕）；
        - 令牌不符（compare_digest 常数时间比较）→ 不发送、不产生记录；
        - 通道未配置 → 返回 sent=False 并说明原因（不让"假成功"流入产品）。
        """
        if decision != "approve":
            return {"sent": False, "reason": "未确认，不发送（无调用记录）"}
        if not confirm_token or not secrets.compare_digest(confirm_token, expected_token):
            return {"sent": False, "reason": "确认令牌不匹配，不发送"}
        if self._channel is None:
            return {"sent": False, "reason": "邮件通道未配置（请在 .env 设置 SMTP_*）"}
        try:
            return self.send(to=email, subject=subject, body=body, ticket=ticket)
        except MailError as exc:
            self.failed.append({"to": email, "subject": subject, "error": str(exc)})
            return {"sent": False, "reason": str(exc)}
