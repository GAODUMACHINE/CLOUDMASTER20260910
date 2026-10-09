"""疏导报告服务：草稿生成 → 前端二次确认 → 发送全链路。

HTTP 语义全部经 ReportServiceError(status_code, detail) 表达，路由统一翻译
HTTPException；「业务性拒绝」（用户未确认 / 已退订）不是错误，返回
{"sent": False, "reason": ...}。

红线：报告只含聚合信息与建议、不含对话原文；发送台账只存交付元数据；
本模块不开文件（DAL 经 storage/reports，消息读取经 checkpointer 的 get_state）。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any

from ..report import build_report

__all__ = [
    "ReportServiceError",
    "draft_report",
    "report_token",
    "report_status",
    "send_report",
    "set_opt_in",
]


class ReportServiceError(Exception):
    """报告服务领域异常：status_code + detail，路由统一翻译 HTTPException。"""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# 报告确认令牌的服务端盐：进程级随机，令牌不可跨进程复用（用户须当次确认）。
_TOKEN_SALT = secrets.token_hex(16)


def report_token(profile_key: str, report_id: str, salt: str | None = None) -> str:
    """报告发送确认令牌（绑定 匿名标识 + 报告编号），前端二次确认时回传。"""
    base = f"{salt or _TOKEN_SALT}:{profile_key}:{report_id}".encode()
    return hmac.new(base, b"confirm", hashlib.sha256).hexdigest()[:32]


def _thread_state(graph: Any, thread_id: str) -> dict[str, Any]:
    """读图状态 values；异常/无 thread 返回 {}。

    与 web/deps.py 各自持有同形副本是有意为之（避免 services→web 反向依赖）。
    """
    try:
        snap = graph.get_state({"configurable": {"thread_id": thread_id}})
        return dict(snap.values or {})
    except Exception:  # noqa: BLE001 -- 报告生成尽力而为
        return {}


def _thread_messages(graph: Any, thread_id: str) -> list[Any]:
    """读图消息列表；异常/无 thread 返回 []。"""
    try:
        snap = graph.get_state({"configurable": {"thread_id": thread_id}})
        return list((snap.values or {}).get("messages") or [])
    except Exception:  # noqa: BLE001 -- 读取尽力而为
        return []


def draft_report(
    *,
    graph: Any,
    store: Any,
    registry: Any,
    mailer: Any,
    profile_key: str,
    salt: str,
) -> dict[str, Any]:
    """生成报告**草稿**（不发送）：落台账并返回确认令牌 + 投递通道状态。

    画像缺失 → 404（先完成注册）；mailer 未配置时 mail_channel_ready=False，
    由前端据此禁用发送而非后端报错（草稿可看、发送须通道）。
    """
    profile = store.get(profile_key) or {}
    if not profile:
        raise ReportServiceError(404, "未找到该匿名标识，请先完成注册")
    state = _thread_state(graph, profile_key)
    draft = build_report(
        profile_key=profile_key,
        profile=profile,
        messages=state.get("messages") or [],
        citations=state.get("citations") or [],
        usage_meta=state.get("usage_meta") or {},
    )
    registry.put_draft(draft)
    return {
        **draft,
        "confirm_token": report_token(profile_key, draft["report_id"], salt),
        "mail_channel_ready": bool(getattr(mailer, "enabled", False)),
        "recipient": profile.get("email", ""),
        "opt_in": bool(profile.get("report_opt_in", True)),
    }


def send_report(
    *,
    store: Any,
    registry: Any,
    mailer: Any,
    report_id: str,
    confirm_token: str,
    decision: str,
    salt: str,
) -> dict[str, Any]:
    """前端二次确认后发送（产品级 HITL）：令牌相符 + 未退订 + 通道已配置，缺一不发送。

    未确认 / 已退订 → {"sent": False, reason}（业务性拒绝，非错误）；草稿缺失 404 /
    重复提交 409 / 令牌不匹配 403 / 画像缺失 404 / 缺邮箱 400 / mailer 未配置 503
    经 ReportServiceError 表达。
    """
    draft = registry.get_draft(report_id)
    if draft is None:
        raise ReportServiceError(404, "报告草稿不存在或已过期")
    if decision != "approve":
        return {"sent": False, "reason": "用户未确认，不发送"}
    if registry.is_sent(report_id):
        raise ReportServiceError(409, "该报告已发送，请勿重复提交")
    profile_key = draft.get("profile_key", "")
    expected = report_token(profile_key, report_id, salt)
    if not confirm_token or not secrets.compare_digest(confirm_token, expected):
        raise ReportServiceError(403, "确认令牌不匹配，不发送")
    profile = store.get(profile_key) or {}
    if not profile:
        raise ReportServiceError(404, "未找到该匿名标识")
    if not profile.get("report_opt_in", True):
        return {"sent": False, "reason": "用户已退订报告，不发送"}
    recipient = str(profile.get("email") or "")
    if not recipient:
        raise ReportServiceError(400, "缺少投递邮箱")
    if mailer is None:
        raise ReportServiceError(503, "mailer 未配置")
    result = mailer.send_if_confirmed(
        email=recipient,
        subject=draft["subject"],
        body=draft["body"],
        decision="approve",
        confirm_token=confirm_token,
        expected_token=expected,
        ticket=report_id,
    )
    if not result.get("sent"):
        # 发送失败必须如实返回，绝不假装成功。
        return {"sent": False, "reason": result.get("reason", "发送失败")}
    record = registry.mark_sent(report_id, result)
    return {"sent": True, "delivery": record}


def report_status(*, store: Any, registry: Any, mailer: Any, profile_key: str) -> dict[str, Any]:
    """本人订阅状态与发送记录：sent_records(profile_key) 按本人过滤。"""
    profile = store.get(profile_key) or {}
    if not profile:
        raise ReportServiceError(404, "未找到该匿名标识")
    sent = registry.sent_records(profile_key)
    return {
        "opt_in": bool(profile.get("report_opt_in", True)),
        "recipient": profile.get("email", ""),
        "mail_channel_ready": bool(getattr(mailer, "enabled", False)),
        "sent_count": len(sent),
        "sent": sent[-5:],
    }


def set_opt_in(*, store: Any, profile_key: str, opt_in: bool) -> dict[str, Any]:
    """退订/再订阅共用（unsubscribe / resubscribe 两端点同一业务动作）。

    写画像白名单字段 report_opt_in（可审计、可再开启）；画像缺失 → 404。
    """
    profile = store.get(profile_key) or {}
    if not profile:
        raise ReportServiceError(404, "未找到该匿名标识")
    profile["report_opt_in"] = opt_in
    store.put(profile_key, profile)
    return {"ok": True, "opt_in": opt_in}
