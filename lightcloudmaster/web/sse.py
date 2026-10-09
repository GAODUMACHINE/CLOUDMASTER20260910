"""真 token SSE 流式。

`graph.stream(..., stream_mode="messages")` 逐 token 下发，事件协议
`data: {"type": "token"|"reply"|"held"|"done", ...}`（JSON）。

设计取舍：
- 选 stream_mode="messages" 而非给模型注入回调：messages 模式天然给出「谁在说话」
  （meta.langgraph_node），节点白名单 {empathic, knowledge} 据此滤掉 crisis 复核 /
  语义筛查的模型输出——判定理由只给审核台值班员，绝不发给用户。
- 零 token 即降级：真模型（ChatOpenAI streaming=True）invoke 期间发 token 回调，
  StubLLM 等替身没有回调 → 一个 token 都收不到时自动降级为单个 reply 事件整段下发。
- 挂起检查前置：L2 待审期间 POST 若推进图，工单会变成「中断态已失效」而永远无法
  闭环；检查实现与 /api/chat 共用 web/deps（单点化）。

红线：白名单外的 chunk 一律丢弃；挂起期间绝不推进图（仍留痕供审核台查看）。
"""

from __future__ import annotations

import json
from typing import Any

from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessageChunk, HumanMessage

from .deps import (
    REVIEW_HOLD_REPLY,
    AppContext,
    _append_user_message,
    _awaiting_human_review,
    _reply_of,
    chat_payload,
    open_escalation,
)

# 节点白名单：只有疏导回复节点（empathic/knowledge）的 token 可下发。
# crisis 节点的模型输出（复核/语义筛查应答）是内部判定材料，绝不进入用户侧事件流。
ALLOWED_NODES = {"empathic", "knowledge"}


def _sse(obj: dict[str, Any]) -> str:
    """dict → 一条 SSE 事件（ensure_ascii=False：中文原文下发，前端免反转义）。"""
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


def stream_response(ctx: AppContext, profile_key: str, text: str) -> StreamingResponse:
    """构造 /api/chat/stream 的流式响应（同步生成器即可，FastAPI 支持迭代器）。"""

    def gen():
        # 挂起检查前置：已有待审工单（thread 停在 human_review）时绝不推进图，否则
        # 图会一路走到 END，把工单变成「中断态已失效」而永远无法闭环。
        if _awaiting_human_review(ctx.graph, profile_key):
            _append_user_message(ctx.graph, profile_key, text)  # 留痕供审核台，不推进图
            pending = ctx.review_ledger.pending_for_thread(profile_key) or {}
            yield _sse({"type": "held", "reply": REVIEW_HOLD_REPLY, "escalation": pending or None})
            yield _sse(
                {
                    "type": "done",
                    "held_for_review": True,
                    "risk_level": pending.get("risk_level") or "high",
                    "next_agent": None,
                    "review_decision": None,
                    "basis_reason": pending.get("basis_reason") or "待人工审核（本轮未推进图）",
                    "escalation": pending or None,
                    "notices": [],
                }
            )
            return

        cfg = {"configurable": {"thread_id": profile_key}}
        # 手工构造与 service_turn 相同的输入（最小画像注入 user_profile，图内只读）。
        # 不能复用 service_turn：那会先 invoke 整轮再回放，流式退化成伪流式。
        payload = {"messages": [HumanMessage(text)], "user_profile": ctx.store.get(profile_key) or {}}
        full_text = ""
        for chunk, meta in ctx.graph.stream(payload, cfg, stream_mode="messages"):
            if meta.get("langgraph_node") not in ALLOWED_NODES:
                continue
            if not isinstance(chunk, AIMessageChunk) and not hasattr(chunk, "content"):
                continue
            piece = str(chunk.content)
            full_text += piece
            yield _sse({"type": "token", "text": piece})

        final = ctx.graph.get_state(cfg).values or {}
        held = _awaiting_human_review(ctx.graph, profile_key)
        escalation = open_escalation(ctx, profile_key, final)
        if held:
            # L2 中断：state 里没有 AI 消息，done 事件经 chat_payload 回占位文案。
            yield _sse({"type": "held", "reply": REVIEW_HOLD_REPLY, "escalation": escalation})
            yield _sse({"type": "done", **chat_payload(ctx, profile_key, final, True, escalation)})
        elif not full_text:
            # 零 token = 无 token 回调的模型（StubLLM 等）：降级单事件整段下发。
            yield _sse({"type": "reply", "text": _reply_of(final.get("messages") or [])})
            yield _sse({"type": "done", **chat_payload(ctx, profile_key, final, False, escalation)})
        else:
            # done 里仍带完整 reply 字段——前端可不组装 token 流、只消费 done 降级渲染。
            yield _sse({"type": "done", **chat_payload(ctx, profile_key, final, False, escalation)})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        # no-cache 防中间层缓存聚合；X-Accel-Buffering 关掉 nginx 反代缓冲（否则 token 会被攒成整段）。
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )