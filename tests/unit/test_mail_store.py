"""单元：邮件报告台账与来信台账（ADR-009）。"""

from __future__ import annotations

import pytest

from cloudmaster.mail_store import InboxStore, MailStoreError, ReportRegistry


@pytest.fixture
def inbox(tmp_path):
    return InboxStore(str(tmp_path / "inbox.jsonl"))


def test_inbox_records_and_dedups_by_uid(inbox):
    assert inbox.record({"uid": "1", "kind": "reply", "ticket": "RP-1"})["recorded"] is True
    dup = inbox.record({"uid": "1", "kind": "reply"})
    assert dup["recorded"] is False
    assert inbox.count() == 1


def test_inbox_rejects_missing_uid(inbox):
    with pytest.raises(MailStoreError):
        inbox.record({"kind": "reply"})


def test_inbox_filters_by_ticket(inbox):
    inbox.record({"uid": "1", "kind": "reply", "ticket": "RP-1"})
    inbox.record({"uid": "2", "kind": "reply", "ticket": "RP-2"})
    assert len(inbox.by_ticket("RP-1")) == 1
    assert inbox.by_ticket("RP-none") == []


def test_inbox_tolerates_corrupt_line(inbox):
    inbox.record({"uid": "1", "kind": "reply"})
    inbox.path.open("a", encoding="utf-8").write("{not json}\n")
    assert inbox.count() == 1  # 坏行跳过，不阻断


def test_report_registry_draft_lifecycle():
    reg = ReportRegistry()
    assert reg.get_draft("RP-1") is None
    reg.put_draft({"report_id": "RP-1", "subject": "s"})
    assert reg.get_draft("RP-1")["subject"] == "s"
    assert reg.is_sent("RP-1") is False
    reg.mark_sent("RP-1", {"to": "u@example.com", "subject": "s", "message_id": "m"})
    assert reg.is_sent("RP-1") is True
    assert reg.sent_records()[0]["to"] == "u@example.com"


def test_report_registry_requires_id():
    with pytest.raises(MailStoreError):
        ReportRegistry().put_draft({"subject": "s"})
