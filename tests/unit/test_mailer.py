"""邮件 HITL（unit，ADR-005 / ADR-009）：未确认/令牌不符绝不发送，拒绝无调用记录。

v1.3.0 起「未配置通道绝不假装成功」：默认 Mailer() 返回 sent=False 并说明原因；
真实发送语义用 RecordingChannel 断言。
"""

from __future__ import annotations

import pytest

from cloudmaster.mailer import Mailer, MailError, OutgoingMail, RecordingChannel, SmtpChannel


def _mailer() -> tuple[Mailer, RecordingChannel]:
    ch = RecordingChannel()
    return Mailer(ch, from_addr="sys@example.com", from_name="CM"), ch


def test_approve_with_token_sends_and_records() -> None:
    mailer, ch = _mailer()
    out = mailer.send_if_confirmed(
        email="u1@example.com",
        subject="s",
        body="b",
        decision="approve",
        confirm_token="tok",
        expected_token="tok",
    )
    assert out["sent"] is True
    assert len(mailer.sent) == 1
    assert len(ch.messages) == 1
    assert ch.messages[0].to == "u1@example.com"


def test_reject_does_not_send_and_no_record() -> None:
    mailer, ch = _mailer()
    out = mailer.send_if_confirmed(
        email="u1@example.com",
        subject="s",
        body="b",
        decision="reject",
        confirm_token="tok",
        expected_token="tok",
    )
    assert out["sent"] is False
    assert mailer.sent == []  # 拒绝：无调用记录
    assert ch.messages == []


def test_token_mismatch_no_send() -> None:
    mailer, ch = _mailer()
    out = mailer.send_if_confirmed(
        email="u1@example.com",
        subject="s",
        body="b",
        decision="approve",
        confirm_token="wrong",
        expected_token="tok",
    )
    assert out["sent"] is False
    assert mailer.sent == []
    assert ch.messages == []


def test_unconfigured_channel_never_fakes_success() -> None:
    """红线：未配置 SMTP 时必须如实报告未发送，绝不假装成功。"""
    mailer = Mailer()
    assert mailer.enabled is False
    out = mailer.send_if_confirmed(
        email="u1@example.com",
        subject="s",
        body="b",
        decision="approve",
        confirm_token="tok",
        expected_token="tok",
    )
    assert out["sent"] is False
    assert "未配置" in out["reason"]
    assert mailer.sent == []


def test_send_without_channel_raises() -> None:
    with pytest.raises(MailError):
        Mailer().send(to="u@example.com", subject="s", body="b")


def test_sent_ledger_does_not_store_body() -> None:
    """隐私：发送台账只留地址/主题/时间/消息号，不落正文。"""
    mailer, _ = _mailer()
    mailer.send(to="u@example.com", subject="s", body="这是报告正文")
    assert set(mailer.sent[0]) == {"to", "subject", "sent_at", "message_id"}
    assert "这是报告正文" not in str(mailer.sent[0])


def test_message_has_ticket_and_utf8_body() -> None:
    ch = RecordingChannel()
    mailer = Mailer(ch, from_addr="sys@example.com", from_name="云上高士")
    mailer.send(to="u@example.com", subject="[RP-1] 报告", body="中文正文", ticket="RP-1")
    msg = ch.messages[0].to_email_message()
    assert msg["To"] == "u@example.com"
    assert "云上高士" in msg["From"]
    assert msg["Message-ID"]
    assert "中文正文" in msg.get_content()


def test_smtp_channel_rejects_unknown_security() -> None:
    with pytest.raises(MailError):
        SmtpChannel(host="smtp.example.com", security="bogus")


def test_smtp_channel_network_failure_is_raised() -> None:
    """连接失败必须抛错（绝不静默），且错误信息带上下文。"""
    ch = SmtpChannel(host="127.0.0.1", port=1, security="plain", timeout=0.5)
    with pytest.raises(MailError):
        ch.send(OutgoingMail(to="u@example.com", subject="s", body="b"))
