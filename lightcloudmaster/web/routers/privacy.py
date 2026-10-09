"""隐私端点：保留期 / 一键导出 / 便捷退出。

导出内容不落服务端额外副本；保留期设置只存匿名标识，不存任何联系方式。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from ...storage.privacy import PrivacyError, export_bundle
from ..deps import AppContext, _delete_thread, _thread_messages, get_ctx
from ..schemas import RetentionReq

router = APIRouter(prefix="/api", tags=["privacy"])


@router.get("/privacy/{profile_key}")
def api_privacy_get(profile_key: str, ctx: Annotated[AppContext, Depends(get_ctx)]) -> dict[str, Any]:
    return {
        "retention": ctx.privacy_store.get_retention(profile_key),
        "purge": ctx.privacy_store.purge_schedule(profile_key),
        "choices": [7, 30, 90],
    }


@router.post("/privacy/{profile_key}/retention")
def api_privacy_retention(
    profile_key: str, req: RetentionReq, ctx: Annotated[AppContext, Depends(get_ctx)]
) -> dict[str, Any]:
    try:
        record = ctx.privacy_store.set_retention(profile_key, req.days)
    except PrivacyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "retention": record, "purge": ctx.privacy_store.purge_schedule(profile_key)}


@router.get("/privacy/{profile_key}/export")
def api_privacy_export(profile_key: str, ctx: Annotated[AppContext, Depends(get_ctx)]) -> dict[str, Any]:
    bundle = export_bundle(
        profile_key=profile_key,
        profile=ctx.store.get(profile_key),
        messages=_thread_messages(ctx.graph, profile_key),
        retention=ctx.privacy_store.get_retention(profile_key),
    )
    try:
        # 审计尽力而为：导出是数据主体权利，审计故障不应拦它。
        ctx.privacy_store.log_export(profile_key)
    except Exception:  # noqa: BLE001
        pass
    return bundle


@router.delete("/profile/{profile_key}")
def api_delete_profile(profile_key: str, ctx: Annotated[AppContext, Depends(get_ctx)]) -> dict[str, Any]:
    # 幂等：重复删除仍 200，不因状态码泄露标识是否存在（防枚举）。
    profile_deleted = ctx.store.delete(profile_key)
    thread_deleted = _delete_thread(ctx.graph, profile_key)
    ctx.privacy_store.forget(profile_key)
    return {"ok": True, "profile_deleted": profile_deleted, "thread_deleted": thread_deleted}
