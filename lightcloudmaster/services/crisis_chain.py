"""危机 L2 人工审核链路（v0.3.0 起，ADR-003；v2.0.0 P7 自根模块迁入 services）。

审计落痕 + 联络桩（不触真实）+ 次日温和回访。红线：测试一律用虚构档案 A1~A7，
绝不影响真实联络/热线；转真实联络须单独评审（ADR-003/ADR-010 待办）。

v2.0.0 P7 新增两件事（ADR-011 §5）：
- enqueue_followup：approve 裁决产生的次日回访**落库**（旧版只落图 state、进程重启
  即丢且审核台不可见）；队列在 storage.followups，交付执行器在 jobs.followups。
- assessment_review_effects：自评工单（source=assessment）裁决的等效副作用——自评
  thread 不是图 thread，无法走图恢复（ADR-011 §4），由本函数直接构造与图恢复
  同形的 audit_log / contact_log / next_followup，web 层据此返回同形响应。
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

    图内 human_review 节点消费本函数（签名与返回形态绝不能变，ADR-003 契约）。
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
    """把裁决产生的回访计划落入持久队列（P7）。

    followup 为 None（block 裁决无回访）时直接返回 None；否则入队并返回队列条目
    （含 id / status=pending / scheduled_at / kind）。旧版 next_followup 只落图 state、
    进程重启即丢；落库后 jobs/followups.run_due 到期交付到审核台待办区
    （done=已交付，回访本身是线下人工动作——ADR-011 §5 语义）。队列 Duck 类型即
    storage.followups.FollowupQueue 的 enqueue 子集，测试可注入桩。
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
    """自评工单（source=assessment）裁决的等效副作用（P4 修 409 死环，ADR-011 §4）。

    自评 thread（assessment:xxxx）不是图 thread，update_state+invoke(None) 必然扑空、
    工单永远无法闭环；本函数按 handle_review 的同构逻辑直接构造审计/联络/回访：
    联络仍为 noop 桩（ADR-003 红线不变），返回形态与图 human_review 恢复后的 state
    键一致（audit_log / contact_log / next_followup），web 层据此返回与 chat 源
    裁决同形的响应。
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
