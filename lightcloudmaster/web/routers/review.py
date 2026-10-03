"""人工审核台端点（ADR-003/ADR-008/ADR-010；v2.0.0 P3 鉴权改 Authorization header）。

- GET /review/pending 新增 followups 键（ADR-011 §5 / P7 回访待办区数据源）：
  delivered_recent(days=7)；followups 队列未启用（None）时返回空列表，前端照常渲染。
- POST /review/decision 双分支（ADR-011 §4，修自评工单 409 死环）：chat 源走「图恢复」
  （三重校验逐字保留：会话存在 → 仍在中断态 → 恢复后必须有审计，否则不许闭环）；
  assessment 源**不碰图**——自评 thread（assessment:xxxx）不是图 thread，
  update_state+invoke(None) 必然扑空，由服务层直接构造同形 audit_log/contact_log/
  next_followup（联络仍为 noop 桩，ADR-003 红线不变）。
- POST /inbox/poll：IMAP 拉取（通道未配置 503；InboxError → 502，绝不吞异常）。

红线：全部端点经 require_reviewer；裁决闭环成功后的回访入队为尽力而为，不改变响应契约。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from ...inbox import InboxError
from ...services.crisis_chain import assessment_review_effects, enqueue_followup
from ...services.mail.ingest import poll_inbox
from ...storage.reviews import CONTACT_KINDS, REVIEW_DECISIONS, ReviewError
from ..deps import (
    AppContext,
    _awaiting_human_review,
    _context_for_review,
    _thread_messages,
    _thread_state,
    get_ctx,
    require_reviewer,
)
from ..schemas import ReviewDecisionReq

router = APIRouter(prefix="/api", tags=["review"])


def _enqueue_followup(
    ctx: AppContext, ticket_id: str, anon_key: str, followup: dict[str, Any] | None
) -> None:
    """approve 裁决产生的次日回访入队（ADR-011 §5）：无回访计划（block 裁决）或
    followups 队列未启用（None）时跳过——回访是可见性职责而非执行职责（ADR-003）。"""
    if ctx.followups is None or followup is None:
        return
    enqueue_followup(ctx.followups, ticket_id=ticket_id, anon_key=anon_key, followup=followup)


@router.get("/review/pending")
def api_review_pending(
    _auth: Annotated[None, Depends(require_reviewer)],
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> dict[str, Any]:
    """待审队列 + 选项词表 + 近 7 日已交付回访（P7 回访待办区数据源）。"""
    followups = ctx.followups.delivered_recent(days=7) if ctx.followups is not None else []
    return {
        "pending": ctx.review_ledger.list_pending(),
        "count": ctx.review_ledger.count_pending(),
        "decisions": REVIEW_DECISIONS,
        "contact_kinds": CONTACT_KINDS,
        "followups": followups,
    }


@router.get("/review/{ticket_id}")
def api_review_detail(
    ticket_id: str,
    _auth: Annotated[None, Depends(require_reviewer)],
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> dict[str, Any]:
    case = ctx.review_ledger.get(ticket_id)
    if case is None:
        raise HTTPException(status_code=404, detail="工单不存在或已闭环")
    thread_id = case.get("thread_id") or ""
    return {
        "case": case,
        "decisions": REVIEW_DECISIONS,
        "contact_kinds": CONTACT_KINDS,
        "context": _context_for_review(_thread_messages(ctx.graph, thread_id)),
        "replies": ctx.inbox_ledger.by_ticket(ticket_id),
    }


@router.post("/review/decision")
def api_review_decision(
    req: ReviewDecisionReq,
    _auth: Annotated[None, Depends(require_reviewer)],
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> dict[str, Any]:
    ticket_id = req.ticket_id
    if not ticket_id:
        raise HTTPException(status_code=400, detail="缺少 ticket_id")
    case = ctx.review_ledger.get(ticket_id)
    if case is None:
        raise HTTPException(status_code=404, detail="工单不存在或已闭环")
    thread_id = case.get("thread_id") or ""

    if case.get("source") == "assessment":
        # assessment 源：自评 thread 不是图 thread，走「图恢复」必然 409 死环（P4 修复）。
        # 服务层直接构造与图恢复同形的审计/联络/回访，台账照常闭环、审计照常留痕。
        effects = assessment_review_effects(
            decision=req.decision,
            reviewer=req.reviewer or "unassigned",
            contact_kind=req.contact_kind,
            basis={"final_level": "self-assessment", "reason": case.get("basis_reason", "")},
        )
        try:
            record = ctx.review_ledger.decide(
                ticket_id, req.decision, reviewer=req.reviewer, contact_kind=req.contact_kind
            )
        except ReviewError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _enqueue_followup(ctx, ticket_id, case.get("profile_key", ""), effects["next_followup"])
        return {
            "ok": True,
            "review": record,
            "audit_log": effects["audit_log"],
            "contact_log": effects["contact_log"],
            "next_followup": effects["next_followup"],
            "pending": ctx.review_ledger.count_pending(),
        }

    cfg = {"configurable": {"thread_id": thread_id}}
    # 裁决必须真正驱动图恢复：先确认该 thread 仍停在 human_review 中断点。
    # 否则（会话已被删除 / 已恢复推进）update_state+invoke(None) 不会经过 human_review，
    # 会返回空 audit_log 却报 ok=True，并让台账闭环——值班员会误以为已处理。
    state = _thread_state(ctx.graph, thread_id)
    if not state:
        raise HTTPException(
            status_code=409,
            detail="该工单对应的会话已不存在（可能已被用户删除数据），无法恢复；请勿据此闭环",
        )
    if not _awaiting_human_review(ctx.graph, thread_id):
        raise HTTPException(
            status_code=409,
            detail="该工单的中断态已失效（会话已恢复或已推进），不能重复裁决",
        )
    try:
        ctx.graph.update_state(cfg, {"review_decision": req.decision})
        resumed = ctx.graph.invoke(None, cfg)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"图恢复失败：{exc}") from exc
    try:
        record = ctx.review_ledger.decide(
            ticket_id, req.decision, reviewer=req.reviewer, contact_kind=req.contact_kind
        )
    except ReviewError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not resumed.get("audit_log"):
        # 兜底：图恢复未落审计，说明链路没闭环，不得静默成功。
        raise HTTPException(
            status_code=500,
            detail="审核结论未写入审计（图恢复异常），工单保持未闭环，请复核后再试",
        )
    _enqueue_followup(ctx, ticket_id, case.get("profile_key", ""), resumed.get("next_followup"))
    return {
        "ok": True,
        "review": record,
        "audit_log": resumed.get("audit_log"),
        "contact_log": resumed.get("contact_log"),
        "next_followup": resumed.get("next_followup"),
        "pending": ctx.review_ledger.count_pending(),
    }


@router.post("/inbox/poll")
def api_inbox_poll(
    _auth: Annotated[None, Depends(require_reviewer)],
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> dict[str, Any]:
    """拉取新来信（内部运维接口）：解析回信/退信/退订并入库（规则在 services.mail.ingest）。"""
    if ctx.inbox is None:
        raise HTTPException(status_code=503, detail="IMAP 收件通道未配置（请设置 IMAP_* 环境变量）")
    try:
        return poll_inbox(inbox=ctx.inbox, ledger=ctx.inbox_ledger, store=ctx.store)
    except InboxError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/inbox")
def api_inbox_list(
    _auth: Annotated[None, Depends(require_reviewer)],
    ctx: Annotated[AppContext, Depends(get_ctx)],
    limit: int = 20,
) -> dict[str, Any]:
    return {
        "count": ctx.inbox_ledger.count(),
        "mails": ctx.inbox_ledger.list_recent(limit),
    }
