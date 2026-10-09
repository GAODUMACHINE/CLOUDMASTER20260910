"""危机 L2 人工审核链路：审计落痕 + 联络桩（不触真实）+ 次日温和回访。

红线：联络为 noop 桩，绝不发起真实联络/热线；转真实联络须单独评审。
enqueue_followup 把 approve 裁决产生的次日回访落库（队列在 storage.followups，
交付执行器在 jobs.followups）；assessment_review_effects 为自评工单裁决构造
与图恢复同形的副作用（自评 thread 不是图 thread，不能走图恢复）。
"""

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
    """L2 人工审核恢复处理：返回 {audit_log, contact_log, next_followup}。

    图内 human_review 节点消费本函数，签名与返回形态不能变。
    """
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


def enqueue_followup(
    queue: Any, *, ticket_id: str, anon_key: str, followup: dict[str, Any] | None
) -> dict[str, Any] | None:
    """把裁决产生的回访计划落入持久队列。

    followup 为 None（block 裁决无回访）时直接返回 None；否则入队并返回队列条目
    （含 id / status=pending / scheduled_at / kind）。落库后 jobs/followups.run_due
    到期交付到审核台待办区。队列鸭子类型即 FollowupQueue 的 enqueue 子集。
    """
    if followup is None:
        return None
    return queue.enqueue(
        ticket_id=ticket_id,
        anon_key=anon_key,
        scheduled_at=followup.get("scheduled_at") or _next_day_iso(),
        kind=followup.get("kind") or "次日温和回访",
    )


def assessment_review_effects(
    *, decision: str, reviewer: str, contact_kind: str, basis: dict[str, Any]
) -> dict[str, Any]:
    """自评工单（source=assessment）裁决的等效副作用。

    自评 thread 不是图 thread，update_state+invoke(None) 必然扑空、工单永远无法
    闭环；本函数按 handle_review 的同构逻辑直接构造审计/联络/回访，返回形态与图
    human_review 恢复后的 state 键一致（audit_log / contact_log / next_followup），
    web 层据此返回与 chat 源裁决同形的响应。
    """
    cs = ContactService()
    result: dict[str, Any] = {"audit_log": [], "contact_log": [], "next_followup": None}
    if decision == "approve":
        contact = cs.notify(contact_kind, reviewer, decision, basis.get("final_level", ""))
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
