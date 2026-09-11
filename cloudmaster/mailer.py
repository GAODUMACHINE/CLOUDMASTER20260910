"""邮件邮件 HITL（ADR-005）：未确认决策绝不 send；拒绝→不 send、无调用记录。
测试一律用内存通道/fake，绝不影响真实中继或邮件。"""

from __future__ import annotations

from typing import Any


class Mailer:
    def __init__(self, channel: Any = None):
        self._channel = channel  # 生产可注入 SMTP 通道；缺省为内存桩
        self.sent: list[dict[str, str]] = []

    def send_if_confirmed(
        self,
        *,
        email: str,
        subject: str,
        body: str,
        decision: str,
        confirm_token: str,
        expected_token: str,
    ) -> dict[str, Any]:
        if decision != "approve":
            return {"sent": False, "reason": "未确认，不发送（无调用记录）"}
        if confirm_token != expected_token:
            return {"sent": False, "reason": "确认令牌不匹配，不发送"}
        self.sent.append({"email": email, "subject": subject})
        if self._channel is not None:
            self._channel.send(email=email, subject=subject, body=body)
        return {"sent": True}
