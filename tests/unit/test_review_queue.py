"""单元：人工审核台账（计划书 3.2.3 / 3.3.1）——闭环唯一性 + 不落对话原文。"""

from __future__ import annotations

import json

import pytest

from cloudmaster.review_queue import CONTACT_KINDS, REVIEW_DECISIONS, ReviewError, ReviewLedger


@pytest.fixture
def ledger(tmp_path):
    return ReviewLedger(str(tmp_path / "reviews.jsonl"))


def test_open_case_is_pending(ledger):
    case = ledger.open_case(
        thread_id="t1",
        risk_level="high",
        basis_level="L2",
        basis_reason="规则层命中",
        context_summary="最近一条用户消息",
    )
    assert case["status"] == "pending" and case["ticket_id"].startswith("HR-")
    assert ledger.count_pending() == 1


def test_same_thread_not_duplicated_while_pending(ledger):
    first = ledger.open_case(thread_id="t1", risk_level="high")
    second = ledger.open_case(thread_id="t1", risk_level="high")
    assert first["ticket_id"] == second["ticket_id"]
    assert ledger.count_pending() == 1


def test_decide_closes_case_and_blocks_second_decision(ledger):
    case = ledger.open_case(thread_id="t1", risk_level="high")
    record = ledger.decide(case["ticket_id"], "approve", reviewer="A1", contact_kind="guardian")
    assert record["contact_label"] == CONTACT_KINDS["guardian"]
    assert ledger.count_pending() == 0
    assert ledger.is_resolved(case["ticket_id"]) is True
    with pytest.raises(ReviewError):
        ledger.decide(case["ticket_id"], "approve")


def test_decide_unknown_ticket_rejected(ledger):
    with pytest.raises(ReviewError):
        ledger.decide("HR-missing", "block")


def test_invalid_decision_and_contact_rejected(ledger):
    case = ledger.open_case(thread_id="t1", risk_level="high")
    with pytest.raises(ReviewError):
        ledger.decide(case["ticket_id"], "maybe")
    with pytest.raises(ReviewError):
        ledger.decide(case["ticket_id"], "approve", contact_kind="stranger")


def test_can_reopen_after_closure(ledger):
    first = ledger.open_case(thread_id="t1", risk_level="high")
    ledger.decide(first["ticket_id"], "block")
    second = ledger.open_case(thread_id="t1", risk_level="high")
    assert second["ticket_id"] != first["ticket_id"]
    assert ledger.count_pending() == 1


def test_ledger_never_stores_conversation_text(ledger):
    """隐私硬约束：台账只留判定依据与摘要，绝不落整段对话原文。"""
    long_text = "用户原文" * 500
    case = ledger.open_case(
        thread_id="t1", risk_level="high", basis_reason=long_text, context_summary=long_text
    )
    blob = json.dumps(case, ensure_ascii=False)
    assert long_text not in blob
    assert len(case["basis_reason"]) <= 500
    assert len(case["context_summary"]) <= 200


def test_decisions_are_closed_set():
    assert set(REVIEW_DECISIONS) == {"approve", "block"}
    assert "none" in CONTACT_KINDS
