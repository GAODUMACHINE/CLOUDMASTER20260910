"""申诉端点（v2.0.0 P3，《办法》第 21 条 / TC-PRIV-006）：POST /api/appeal。

四类申诉词表与受理台账（append-only、可审计）在 storage.appeals；本层只翻译
AppealError → 400。红线：仅记录申诉所需最小字段，不含姓名/联系方式。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from ...storage.appeals import AppealError
from ..deps import AppContext, get_ctx
from ..schemas import AppealReq

router = APIRouter(prefix="/api", tags=["appeals"])


@router.post("/appeal")
def api_appeal(req: AppealReq, ctx: Annotated[AppContext, Depends(get_ctx)]) -> dict[str, Any]:
    """提交申诉：返回可追踪工单号（AP-xxxxxx）与受理时间。"""
    try:
        record = ctx.appeal_store.submit(req.kind, req.text, req.profile_key)
    except AppealError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "ticket_id": record["ticket_id"], "submitted_at": record["submitted_at"]}
