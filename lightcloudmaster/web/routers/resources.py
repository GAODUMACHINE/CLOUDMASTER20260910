"""转介资源端点：GET /api/resources 与热线录入。

红线：本页不硬编码任何真实热线号码——默认下发空列表，只有经人工审核录入
（require_reviewer + 审核人署名必填）的号码才会下发给前端；紧急情况引导拨打当地急救电话。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from ...storage.appeals import APPEAL_KINDS
from ...storage.resources import ResourceError
from ..deps import AppContext, get_ctx, require_reviewer
from ..schemas import ResourceRegisterReq

router = APIRouter(prefix="/api", tags=["resources"])

RESOURCE_ENTRIES: list[dict[str, Any]] = [
    {
        "kind": "guardian",
        "title": "联系监护人或可信任的成年人",
        "detail": "把此刻的感受告诉身边可信任的人，让他们陪着你。",
    },
    {
        "kind": "school",
        "title": "学校心理健康教育与咨询中心",
        "detail": "多数高校设有免费心理咨询，可线上或线下预约。",
    },
    {
        "kind": "offline",
        "title": "当地精神卫生中心 / 医院心理科",
        "detail": "如需进一步评估，可到线下专业机构就诊。",
    },
    {
        "kind": "emergency",
        "title": "紧急情况",
        "detail": ("若你有立即伤害自己的想法，请立即拨打当地急救电话或前往就近医院急诊，并联系可信任的人。"),
    },
]

RESOURCES_NOTE = "本页不提供未经人工审核的热线号码；如遇紧急情况请拨打当地急救电话或就近就医。"


@router.get("/resources")
def api_resources(ctx: Annotated[AppContext, Depends(get_ctx)]) -> dict[str, Any]:
    return {
        "note": RESOURCES_NOTE,
        "entries": RESOURCE_ENTRIES,
        "hotlines": ctx.resource_store.approved(),
        "appeals": {"submit_url": "/api/appeal", "kinds": APPEAL_KINDS},
    }


@router.post("/resources/hotline")
def api_resource_register(
    req: ResourceRegisterReq,
    _auth: Annotated[None, Depends(require_reviewer)],
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> dict[str, Any]:
    """审核台录入热线：须审核人署名（无署名 400，未经人工审核的资源一律不下发）。"""
    try:
        record = ctx.resource_store.add(
            title=req.title,
            detail=req.detail,
            kind=req.kind,
            tel=req.tel,
            reviewer=req.reviewer,
        )
    except ResourceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "hotline": record}
