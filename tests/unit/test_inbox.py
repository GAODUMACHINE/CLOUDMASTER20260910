"""单元：邮件接收解析（ADR-009）——回信/退信/自动回复/退订识别，纯函数离线可测。"""

from __future__ import annotations

from email.message import EmailMessage

import pytest

from cloudmaster.inbox import (
    KIND_AUTO,
    KIND_BOUNCE,
    KIND_OTHER,
    KIND_REPLY,
    ImapInbox,
    InboxError,
    parse_message,
)


def _raw(subject: str, *, frm: str = "u@example.com", body: str = "hello") -> bytes:
    m = EmailMessage()
    m["From"] = frm
    m["To"] = "sys@example.com"
    m["Subject"] = subject
    m.set_content(body)
    return m.as_bytes()


def test_reply_with_ticket_is_classified():
    mail = parse_message(_raw("Re: [RP-abc123] 你的阶段性疏导报告"))
    assert mail.kind == KIND_REPLY
    assert mail.ticket == "RP-abc123"


def test_reply_to_crisis_ticket_is_linked():
    mail = parse_message(_raw("Re: [HR-deadbeef] 人工跟进"))
    assert mail.kind == KIND_REPLY and mail.ticket == "HR-deadbeef"


def test_subject_without_ticket_is_other():
    assert parse_message(_raw("随便聊聊")).kind == KIND_OTHER


def test_bounce_is_detected():
    for subject in (
        "Mail Delivery Failed: returning message",
        "Undelivered Mail Returned to Sender",
        "退信通知",
    ):
        mail = parse_message(_raw(subject, frm="MAILER-DAEMON@example.com"))
        assert mail.kind == KIND_BOUNCE, subject


def test_auto_reply_is_detected():
    assert parse_message(_raw("Out of office")).kind == KIND_AUTO
    assert parse_message(_raw("自动回复：我在休假")).kind == KIND_AUTO


def test_stop_requested_english_and_chinese():
    assert parse_message(_raw("STOP")).stop_requested is True
    assert parse_message(_raw("退订")).stop_requested is True
    assert parse_message(_raw("你好", body="请不要再发报告了")).stop_requested is True
    assert parse_message(_raw("继续加油", body="谢谢你")).stop_requested is False


def test_body_is_truncated_and_attachment_ignored():
    mail = parse_message(_raw("你好", body="x" * 5000), body_limit=100)
    assert len(mail.body) == 100
    # 含附件的多部分邮件：只取 text/plain，跳过附件
    m = EmailMessage()
    m["From"] = "u@example.com"
    m["Subject"] = "[RP-1] x"
    m.set_content("正文内容")
    m.add_attachment(b"\x00\x01", maintype="application", subtype="octet-stream", filename="a.bin")
    parsed = parse_message(m.as_bytes())
    assert "正文内容" in parsed.body
    assert "a.bin" not in parsed.body


def test_uid_and_size_recorded():
    mail = parse_message(_raw("hi"), uid="77")
    assert mail.uid == "77" and mail.raw_size > 0
    assert mail.to_record()["uid"] == "77"


def test_imap_connection_failure_raises():
    """连接失败必须抛 InboxError（绝不静默返回空列表）。"""
    inbox = ImapInbox(host="127.0.0.1", port=1, user="u", password="p", timeout=0.5)
    with pytest.raises(InboxError):
        inbox.fetch_unseen()
