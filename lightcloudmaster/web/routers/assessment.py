"""情绪自评端点（v2.0.0 P3，功能对照表 #7）。

GET /items 下发条目与四档选项（措辞自拟、不含分值，前端只回传 value）；
POST /assessment 由 services.assessment.submit_assessment 计分并开案
（urgent 工单带 source=assessment，供审核台专用闭环分支，修 409 死环）。
红线：结果只呈现「区间 + 建议动作」，绝不输出分数诊断或病名（文案在服务/量表层）。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from ...assessment import CHOICE_LABELS, ITEMS
from ...services.assessment import AssessmentError, submit_assessment
from ..deps import AppContext, get_ctx
from ..schemas import AssessmentReq

router = APIRouter(prefix="/api", tags=["assessment"])


@router.get("/assessment/items")
def api_assessment_items() -> dict[str, Any]:
    return {
        "items": list(ITEMS),
        "choices": [{"value": k, "label": v} for k, v in CHOICE_LABELS.items()],
        "disclaimer": "自评结果不构成诊断，仅供参考。",
    }


@router.post("/assessment")
def api_assessment(req: AssessmentReq, ctx: Annotated[AppContext, Depends(get_ctx)]) -> dict[str, Any]:
    """提交自评：纯规则计分（不调模型）；urgent 区间在服务层升级 L2 并登记待审工单。"""
    try:
        return submit_assessment(ledger=ctx.review_ledger, answers=req.answers)
    except AssessmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
