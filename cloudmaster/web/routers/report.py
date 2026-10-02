"""疏导报告端点（ADR-009；v2.0.0 P3 起业务规则全部在 services/report）。

草稿生成（不发送）→ 前端二次确认（一次一密令牌 + opt-in + 通道就绪）→ SMTP 发送 →
退订/再订阅。本层只做错误翻译：ReportServiceError 携带 (status_code, detail) 原样
转 HTTPException；sent=False 属正常业务结果（用户未确认/已退订/通道未配置），一律 200
如实返回——红线：发送失败绝不假装成功。

salt 经 AppContext 注入：装配处生成一次、贯穿草稿（发令牌）与发送（验令牌），
跨进程不可复用（用户须当次确认）。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from ...services.report import (
    ReportServiceError,
    draft_report,
    report_status,
    send_report,
    set_opt_in,
)
from ..deps import AppContext, get_ctx
from ..schemas import ReportSendReq

router = APIRouter(prefix="/api", tags=["report"])


@router.get("/report/{profile_key}")
def api_report_draft(profile_key: str, ctx: Annotated[AppContext, Depends(get_ctx)]) -> dict[str, Any]:
    """生成报告**草稿**（不发送）。确认令牌 / 通道状态 / 收件人 / 订阅态由服务层补齐。"""
    try:
        return draft_report(
            graph=ctx.graph,
            store=ctx.store,
            registry=ctx.report_registry,
            mailer=ctx.mailer,
            profile_key=profile_key,
            salt=ctx.report_salt,
        )
    except ReportServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/report/send")
def api_report_send(req: ReportSendReq, ctx: Annotated[AppContext, Depends(get_ctx)]) -> dict[str, Any]:
    """前端二次确认后发送（产品级 HITL）：令牌相符 + 已订阅 + 通道已配置才真发。"""
    try:
        return send_report(
            store=ctx.store,
            registry=ctx.report_registry,
            mailer=ctx.mailer,
            report_id=req.report_id,
            confirm_token=req.confirm_token,
            decision=req.decision,
            salt=ctx.report_salt,
        )
    except ReportServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/report/status/{profile_key}")
def api_report_status(profile_key: str, ctx: Annotated[AppContext, Depends(get_ctx)]) -> dict[str, Any]:
    """本人报告状态（订阅态/收件人/通道/最近发送记录）——v2.0.0 起按本人过滤（修跨用户泄漏）。"""
    try:
        return report_status(
            store=ctx.store,
            registry=ctx.report_registry,
            mailer=ctx.mailer,
            profile_key=profile_key,
        )
    except ReportServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/report/unsubscribe/{profile_key}")
def api_report_unsubscribe(profile_key: str, ctx: Annotated[AppContext, Depends(get_ctx)]) -> dict[str, Any]:
    """前端退订：写入画像白名单字段 report_opt_in=False（可审计、可再开启）。"""
    try:
        set_opt_in(store=ctx.store, profile_key=profile_key, opt_in=False)
    except ReportServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {"ok": True, "opt_in": False}


@router.post("/report/resubscribe/{profile_key}")
def api_report_resubscribe(profile_key: str, ctx: Annotated[AppContext, Depends(get_ctx)]) -> dict[str, Any]:
    """重新开启报告订阅（与退订对称）。"""
    try:
        set_opt_in(store=ctx.store, profile_key=profile_key, opt_in=True)
    except ReportServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {"ok": True, "opt_in": True}
