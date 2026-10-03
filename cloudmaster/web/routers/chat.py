"""对话端点（v2.0.0 P3）：POST /api/chat 与 /api/chat/stream（ADR-011 §2/§3）。

鉴权改 Bearer（ADR-007：匿名 ID 即凭证）：匿名标识不进请求体，缺凭证 401。
挂起检查（L2 待审期间绝不推进图）与危机开案、响应组装（chat_payload）单点在
web/deps.py——两个端点共用同一份实现，谁也不许再各自复制（旧 stream 端点漏掉
挂起检查就是 L2 绕过事故的根因）。红线：挂起期间自动回复暂停，仅留痕 + 占位文案。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from ...services.session import service_turn
from ..deps import (
    REVIEW_HOLD_REPLY,
    AppContext,
    _append_user_message,
    _awaiting_human_review,
    chat_payload,
    get_ctx,
    open_escalation,
    require_profile,
)
from ..schemas import ChatReq
from ..sse import stream_response

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
def api_chat(
    req: ChatReq,
    profile_key: Annotated[str, Depends(require_profile)],
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> dict[str, Any]:
    cfg = {"configurable": {"thread_id": profile_key}}
    # 已有待审工单（thread 停在 human_review）时：自动回复暂停，且**绝不推进图**。
    # 若照常 invoke，图会执行 human_review(decision=pending) 一路走到 END，把工单变成
    # 「中断态已失效」而永远无法闭环——等于用户发一条非危机消息就能绕过人工审核。
    # 仍把这条消息写进 state，供审核台看到完整上下文。
    if _awaiting_human_review(ctx.graph, profile_key):
        _append_user_message(ctx.graph, profile_key, req.text)
        pending = ctx.review_ledger.pending_for_thread(profile_key) or {}
        return {
            "reply": REVIEW_HOLD_REPLY,
            "risk_level": pending.get("risk_level") or "high",
            "next_agent": None,
            "review_decision": None,
            "basis_reason": pending.get("basis_reason") or "待人工审核（本轮未推进图）",
            "escalation": pending or None,
            "held_for_review": True,
            "notices": [],
        }
    res = service_turn(ctx.graph, ctx.store, profile_key, req.text, cfg)
    held = _awaiting_human_review(ctx.graph, profile_key)
    escalation = open_escalation(ctx, profile_key, res)
    return chat_payload(ctx, profile_key, res, held, escalation)


@router.post("/chat/stream")
def api_stream(
    req: ChatReq,
    profile_key: Annotated[str, Depends(require_profile)],
    ctx: Annotated[AppContext, Depends(get_ctx)],
):
    """真 token SSE：事件协议（token/reply/held/done）、节点白名单与挂起检查见 web/sse.py。"""
    return stream_response(ctx, profile_key, req.text)
