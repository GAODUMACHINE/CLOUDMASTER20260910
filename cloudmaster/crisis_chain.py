"""危机 L2 人工审核链路（v0.3.0，ADR-003）：审计落痕 + 联络桩(不触真实) + 次日温和回访。
红线：测试一律用虚构档案 A1~A7，绝不影响真实联络/热线。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

AUDIT_REVIEWER_FICTION = "HUMAN-REVIEW-A1"  # 虚构审核标识，非真实个人


class ContactService:
    """联络桩：默认 enabled=False 只写 noop 审计，不发起真实联络。"""

    def __init__(self, enabled: bool = False):
        self._enabled = enabled

    def notify(self, contact_kind: str, reviewer: str, decision: str, basis_level: str) -> dict[str, Any]:
        action = "requested-to-human(生产人工执行)" if self._enabled else "noop-stub(不触真实联络)"
        return {
            "contact_kind": contact_kind,
            "reviewer": reviewer,
            "decision": decision,
            "basis_level": basis_level,
            "time": datetime.now(UTC).isoformat(),
            "action": action,
            "safety": "fiction-only(A1~A7)，不发真实联络",
        }


def audit_record(
    basis: dict[str, Any], decision: str, reviewer: str, contact_log_entry: dict | None = None
) -> dict[str, Any]:
    return {
        "time": datetime.now(UTC).isoformat(),
        "basis_level": basis.get("final_level"),
        "basis_reason": basis.get("reason"),
        "reviewer": reviewer,
        "decision": decision,
        "contact_action": (contact_log_entry or {}).get("action") if contact_log_entry else "none",
    }


def _next_day_iso() -> str:
    return (datetime.now(UTC) + timedelta(days=1)).isoformat()


def handle_review(
    basis: dict[str, Any],
    decision: str,
    contact_service: ContactService | None = None,
    reviewer: str = AUDIT_REVIEWER_FICTION,
) -> dict[str, Any]:
    """L2 人工审核恢复处理：返回 {audit_log, contact_log, next_followup}。"""
    cs = contact_service or ContactService()
    result: dict[str, Any] = {"audit_log": [], "contact_log": [], "next_followup": None}
    if decision == "approve":
        contact = cs.notify("guardian", reviewer, decision, basis.get("final_level", ""))
        result["contact_log"] = [contact]
        result["audit_log"] = [audit_record(basis, decision, reviewer, contact)]
        result["next_followup"] = {
            "scheduled_at": _next_day_iso(),
            "kind": "次日温和回访",
            "reviewer": reviewer,
        }
    elif decision == "block":
        result["audit_log"] = [audit_record(basis, decision, reviewer)]
    return result
