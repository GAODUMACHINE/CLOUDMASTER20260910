"""危机 L2 链路（unit，ADR-003）：联络桩不触真实 + 审计完整 + 回访安排。"""

from __future__ import annotations

from cloudmaster.crisis_chain import ContactService, handle_review

B = {"final_level": "L2", "reason": "规则命中2个关键词"}


def test_contact_stub_noop_never_real():
    cs = ContactService()
    rec = cs.notify("guardian", "REVA1", "approve", "L2")
    assert rec["action"] == "noop-stub(不触真实联络)"
    assert rec["safety"] == "fiction-only(A1~A7)，不发真实联络"


def test_approve_writes_audit_and_followup():
    out = handle_review(B, "approve")
    assert out["audit_log"] and out["contact_log"] and out["next_followup"]
    a = out["audit_log"][0]
    for k in ("time", "basis_level", "basis_reason", "reviewer", "decision", "contact_action"):
        assert k in a
    assert a["decision"] == "approve"
    assert a["contact_action"] == "noop-stub(不触真实联络)"
    assert out["next_followup"]["kind"] == "次日温和回访"


def test_block_no_contact():
    out = handle_review(B, "block")
    assert out["audit_log"] and out["contact_log"] == [] and out["next_followup"] is None


def test_enabled_is_human_request_only():
    cs = ContactService(enabled=True)
    rec = cs.notify("guardian", "REVA1", "approve", "L2")
    assert rec["action"] == "requested-to-human(生产人工执行)"
