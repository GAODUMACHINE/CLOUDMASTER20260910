"""邮件 HITL（unit，ADR-005）：未确认/令牌不符绝不发送，拒绝无调用记录。"""

from __future__ import annotations

from cloudmaster.mailer import Mailer


def test_approve_with_token_sends_and_records() -> None:
    mailer = Mailer()
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


def test_reject_does_not_send_and_no_record() -> None:
    mailer = Mailer()
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


def test_token_mismatch_no_send() -> None:
    mailer = Mailer()
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
