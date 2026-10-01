"""Web 服务（v0.5.0 起，ADR-005；v1.1.0 补匿名隔离与申诉；v1.2.0 补计划书缺口；v1.3.0 补邮件收发）。
测试一律注入 fake graph/store/mailer，禁止触网/真实模型/真实邮件。

v1.3.0 新增（ADR-009，计划书 3.1.3 / 3.2.3 / P1）：
- 注册邮箱采集（最小必要的唯一例外，可查看/可删除/可退订）；
- 疏导报告：草稿生成 → 前端二次确认 → SMTP 发送（产品级 HITL）；
- IMAP 收信：回信/退信/退订解析入库，STOP 自动退订。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import service as svc
from .appeals import APPEAL_KINDS, AppealError, AppealStore
from .assessment import CHOICE_LABELS, ITEMS, AssessmentError
from .assessment import score as score_assessment
from .inbox import ImapInbox, InboxError
from .mail_store import InboxStore, ReportRegistry
from .privacy import DEFAULT_RETENTION_DAYS, PrivacyError, PrivacyStore, export_bundle
from .profile_store import ProfileStore
from .registration import RegistrationError, register
from .report import build_report
from .resources import ResourceError, ResourceStore
from .review_queue import CONTACT_KINDS, REVIEW_DECISIONS, ReviewError, ReviewLedger


class RegisterReq(BaseModel):
    age: int
    email: str = ""
    guardian_contact_available: bool = False
    dependency_tendency: bool = False


class ChatReq(BaseModel):
    profile_key: str
    text: str


class EmailConfirmReq(BaseModel):
    email: str
    subject: str
    body: str
    decision: str
    confirm_token: str


class AppealReq(BaseModel):
    kind: str
    text: str
    profile_key: str = ""


class AssessmentReq(BaseModel):
    answers: dict[str, str]


class RetentionReq(BaseModel):
    days: int


class ReviewDecisionReq(BaseModel):
    decision: str
    ticket_id: str = ""
    reviewer: str = ""
    contact_kind: str = "guardian"


class ResourceRegisterReq(BaseModel):
    title: str
    detail: str = ""
    kind: str = "school"
    tel: str = ""
    reviewer: str = ""


class ReportSendReq(BaseModel):
    report_id: str
    confirm_token: str
    decision: str = "approve"


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

# L2 中断态下对用户的占位文案。
# 背景：`interrupt_before=["human_review"]` 在 human_review **之前**中断，此刻 state 里只有用户那条
# HumanMessage，若仍取 msgs[-1] 会把用户自己的话当成"AI 回复"回显。中断期间自动回复本就应该暂停，
# 故统一返回该占位文案（不含任何热线号码，仅给就地安全提示）。
REVIEW_HOLD_REPLY = (
    "你的表达可能涉及较高的风险。为保障你的安全，本轮自动回复已暂停，已转交人工审核台跟进。"
    "请先与信任的人、监护人或身边可信任的成年人待在一起；"
    "如有立即的危险，请立即拨打当地急救电话或前往就近医院急诊。"
)


def _reply_of(msgs: list[Any]) -> str:
    """取最后一条 AI 消息作为回复；无 AI 消息返回空串。

    v2.0.0 P2 回显守卫：裸取 msgs[-1] 在「图结束时最后一条是用户消息」的路径上
    （如防死循环强制 end）会把用户自己的话回显成 AI 回复；倒序找最近一条 AI 消息即可。
    time_guard 的非阻断提示也是 AI 消息：若其后无疏导回复（收尾短路），该提示本身
    就是当轮回复——语义正确。
    """
    for m in reversed(msgs):
        if getattr(m, "type", "") == "ai":
            return str(m.content)
    return ""


# 报告确认令牌的服务端盐：进程级随机，令牌不可跨进程复用（用户须当次确认）。
_TOKEN_SALT = secrets.token_hex(16)


def report_token(profile_key: str, report_id: str, salt: str | None = None) -> str:
    """报告发送确认令牌（绑定 匿名标识 + 报告编号），前端二次确认时回传。"""
    base = f"{salt or _TOKEN_SALT}:{profile_key}:{report_id}".encode()
    return hmac.new(base, b"confirm", hashlib.sha256).hexdigest()[:32]


def _delete_thread(graph: Any, thread_id: str) -> bool:
    fn = getattr(getattr(graph, "checkpointer", None), "delete_thread", None)
    if fn is None:
        return False
    try:
        fn(thread_id)
    except Exception:  # noqa: BLE001 -- 用户退出优先
        return False
    return True


def _thread_messages(graph: Any, thread_id: str) -> list[Any]:
    try:
        snap = graph.get_state({"configurable": {"thread_id": thread_id}})
        return list((snap.values or {}).get("messages") or [])
    except Exception:  # noqa: BLE001 -- 导出/报告尽力而为
        return []


def _thread_state(graph: Any, thread_id: str) -> dict[str, Any]:
    try:
        snap = graph.get_state({"configurable": {"thread_id": thread_id}})
        return dict(snap.values or {})
    except Exception:  # noqa: BLE001
        return {}


def _last_user_text(messages: list[Any]) -> str:
    for m in reversed(messages):
        if getattr(m, "type", "") == "human":
            return str(getattr(m, "content", ""))
    return ""


def _context_summary(messages: list[Any], limit: int = 200) -> str:
    return _last_user_text(messages)[:limit]


def _context_for_review(messages: list[Any], limit: int = 6) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for m in messages[-limit:]:
        role = "user" if getattr(m, "type", "") == "human" else "ai"
        out.append({"role": role, "text": str(getattr(m, "content", ""))[:300]})
    return out


def _thread_next(graph: Any, thread_id: str) -> tuple[str, ...]:
    """该 thread 的下一步待执行节点；异常/无 thread 时返回空元组。"""
    try:
        snap = graph.get_state({"configurable": {"thread_id": thread_id}})
        return tuple(snap.next or ())
    except Exception:  # noqa: BLE001 -- 判定中断态尽力而为
        return ()


def _awaiting_human_review(graph: Any, thread_id: str) -> bool:
    """thread 是否停在 human_review 中断点（L2 待审、自动回复已暂停）。"""
    return "human_review" in _thread_next(graph, thread_id)


def _append_user_message(graph: Any, thread_id: str, text: str) -> bool:
    """把用户消息追加进 state（供审核台查看），但不推进图。"""
    from langchain_core.messages import HumanMessage

    try:
        graph.update_state({"configurable": {"thread_id": thread_id}}, {"messages": [HumanMessage(text)]})
    except Exception:  # noqa: BLE001 -- 留痕尽力而为，不阻断挂起态返回
        return False
    return True


def create_app(
    graph: Any,
    store: ProfileStore,
    mailer: Any = None,
    expected_token: str = "token",
    appeals: AppealStore | None = None,
    reviews: ReviewLedger | None = None,
    privacy: PrivacyStore | None = None,
    resources: ResourceStore | None = None,
    reviewer_token: str = "",
    inbox_store: InboxStore | None = None,
    reports: ReportRegistry | None = None,
    inbox: ImapInbox | None = None,
    report_salt: str | None = None,
) -> FastAPI:
    app = FastAPI(title="CLOUDMASTER", version="1.3.0")
    appeal_store = appeals or AppealStore()
    review_ledger = reviews or ReviewLedger()
    privacy_store = privacy or PrivacyStore()
    resource_store = resources or ResourceStore()
    inbox_ledger = inbox_store or InboxStore()
    report_registry = reports or ReportRegistry()
    salt = report_salt or _TOKEN_SALT

    _frontend = Path(__file__).resolve().parent.parent / "frontend"
    app.mount("/web", StaticFiles(directory=str(_frontend), html=True), name="web")

    @app.get("/", include_in_schema=False)
    def index() -> RedirectResponse:
        """根路径直接进用户前端。

        此前 `/` 与 `/web/` 都是 404，必须一字不差地输入 `/web/cloud-glass/` 才能进入，
        很容易被误判成「前端坏了/进不去」。统一由根路径跳转（`/web/` 由 frontend/index.html 承接）。
        """
        return RedirectResponse(url="/web/cloud-glass/")

    @app.post("/api/register")
    def api_register(req: RegisterReq) -> dict:
        try:
            profile = register(
                age=req.age,
                guardian_contact_available=req.guardian_contact_available,
                dependency_tendency=req.dependency_tendency,
                email=req.email,
            )
        except RegistrationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        key = "anon-" + secrets.token_urlsafe(12)
        store.put(key, profile)
        try:
            privacy_store.set_retention(key, DEFAULT_RETENTION_DAYS, now=datetime.now(UTC))
        except PrivacyError:
            pass
        return {"ok": True, "profile_key": key}

    @app.post("/api/chat")
    def api_chat(req: ChatReq) -> dict:
        cfg = {"configurable": {"thread_id": req.profile_key}}
        # 已有待审工单（thread 停在 human_review）时：自动回复暂停，且**绝不推进图**。
        # 若照常 invoke，图会执行 human_review(decision=pending) 一路走到 END，把工单变成
        # 「中断态已失效」而永远无法闭环——等于用户发一条非危机消息就能绕过人工审核。
        # 仍把这条消息写进 state，供审核台看到完整上下文。
        if _awaiting_human_review(graph, req.profile_key):
            _append_user_message(graph, req.profile_key, req.text)
            pending = review_ledger.pending_for_thread(req.profile_key) or {}
            return {
                "reply": REVIEW_HOLD_REPLY,
                "risk_level": pending.get("risk_level") or "high",
                "next_agent": None,
                "review_decision": None,
                "basis_reason": pending.get("basis_reason") or "待人工审核（本轮未推进图）",
                "escalation": pending or None,
                "held_for_review": True,
            }
        res = svc.service_turn(graph, store, req.profile_key, req.text, cfg)
        msgs = res.get("messages") or []
        basis = res.get("crisis_basis") or {}
        risk = res.get("risk_level")
        escalation = None
        # L2 会停在 human_review 中断点：此时 state 里没有 AI 消息，必须返回占位文案，
        # 否则会把用户自己的话当"AI 回复"回显（前端会把用户那条消息再显示一遍）。
        held = _awaiting_human_review(graph, req.profile_key)
        if risk == "high":
            escalation = review_ledger.open_case(
                thread_id=req.profile_key,
                risk_level=risk,
                basis_level=basis.get("final_level", ""),
                basis_reason=basis.get("reason", ""),
                profile_key=req.profile_key,
                context_summary=_context_summary(_thread_messages(graph, req.profile_key)),
            )
        reply = REVIEW_HOLD_REPLY if held else _reply_of(msgs)
        return {
            "reply": reply,
            "risk_level": risk,
            "next_agent": res.get("next_agent"),
            "review_decision": res.get("review_decision"),
            "basis_reason": basis.get("reason"),
            "escalation": escalation,
            "held_for_review": held,
        }

    @app.post("/api/chat/stream")
    def api_stream(req: ChatReq):
        from fastapi.responses import StreamingResponse

        cfg = {"configurable": {"thread_id": req.profile_key}}
        res = svc.service_turn(graph, store, req.profile_key, req.text, cfg)
        msgs = res.get("messages") or []
        return StreamingResponse(iter("data: " + _reply_of(msgs) + "\n\n"), media_type="text/event-stream")

    # ---- 邮件：报告草稿 / 二次确认发送 / 收信 / 退订（ADR-009） ----
    def _profile_of(profile_key: str) -> dict[str, Any]:
        return store.get(profile_key) or {}

    @app.get("/api/report/{profile_key}")
    def api_report_draft(profile_key: str) -> dict:
        """生成报告**草稿**（不发送）。返回确认令牌供前端二次确认。"""
        profile = _profile_of(profile_key)
        if not profile:
            raise HTTPException(status_code=404, detail="未找到该匿名标识，请先完成注册")
        state = _thread_state(graph, profile_key)
        draft = build_report(
            profile_key=profile_key,
            profile=profile,
            messages=state.get("messages") or [],
            citations=state.get("citations") or [],
            usage_meta=state.get("usage_meta") or {},
        )
        report_registry.put_draft(draft)
        draft = dict(draft)
        draft["confirm_token"] = report_token(profile_key, draft["report_id"], salt)
        draft["mail_channel_ready"] = bool(getattr(mailer, "enabled", False))
        draft["recipient"] = profile.get("email", "")
        draft["opt_in"] = bool(profile.get("report_opt_in", True))
        return draft

    @app.post("/api/report/send")
    def api_report_send(req: ReportSendReq) -> dict:
        """前端二次确认后发送（产品级 HITL）：须令牌相符 + 已开启报告 + 通道已配置。"""
        draft = report_registry.get_draft(req.report_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="报告草稿不存在或已过期")
        if req.decision != "approve":
            return {"sent": False, "reason": "用户未确认，不发送"}
        if report_registry.is_sent(req.report_id):
            raise HTTPException(status_code=409, detail="该报告已发送，请勿重复提交")
        profile_key = draft.get("profile_key", "")
        expected = report_token(profile_key, req.report_id, salt)
        if not req.confirm_token or not secrets.compare_digest(req.confirm_token, expected):
            raise HTTPException(status_code=403, detail="确认令牌不匹配，不发送")
        profile = _profile_of(profile_key)
        if not profile:
            raise HTTPException(status_code=404, detail="未找到该匿名标识")
        if not profile.get("report_opt_in", True):
            return {"sent": False, "reason": "用户已退订报告，不发送"}
        recipient = str(profile.get("email") or "")
        if not recipient:
            raise HTTPException(status_code=400, detail="缺少投递邮箱")
        if mailer is None:
            raise HTTPException(status_code=503, detail="mailer 未配置")
        result = mailer.send_if_confirmed(
            email=recipient,
            subject=draft["subject"],
            body=draft["body"],
            decision="approve",
            confirm_token=req.confirm_token,
            expected_token=expected,
            ticket=req.report_id,
        )
        if not result.get("sent"):
            # 发送失败必须如实返回，绝不假装成功。
            return {"sent": False, "reason": result.get("reason", "发送失败")}
        record = report_registry.mark_sent(req.report_id, result)
        return {"sent": True, "delivery": record}

    @app.get("/api/report/status/{profile_key}")
    def api_report_status(profile_key: str) -> dict:
        profile = _profile_of(profile_key)
        if not profile:
            raise HTTPException(status_code=404, detail="未找到该匿名标识")
        sent = [r for r in report_registry.sent_records()]
        return {
            "opt_in": bool(profile.get("report_opt_in", True)),
            "recipient": profile.get("email", ""),
            "mail_channel_ready": bool(getattr(mailer, "enabled", False)),
            "sent_count": len(sent),
            "sent": sent[-5:],
        }

    @app.post("/api/report/unsubscribe/{profile_key}")
    def api_report_unsubscribe(profile_key: str) -> dict:
        """前端退订：写入画像白名单字段 report_opt_in=False（可审计、可再开启）。"""
        profile = _profile_of(profile_key)
        if not profile:
            raise HTTPException(status_code=404, detail="未找到该匿名标识")
        profile["report_opt_in"] = False
        store.put(profile_key, profile)
        return {"ok": True, "opt_in": False}

    @app.post("/api/report/resubscribe/{profile_key}")
    def api_report_resubscribe(profile_key: str) -> dict:
        profile = _profile_of(profile_key)
        if not profile:
            raise HTTPException(status_code=404, detail="未找到该匿名标识")
        profile["report_opt_in"] = True
        store.put(profile_key, profile)
        return {"ok": True, "opt_in": True}

    @app.post("/api/inbox/poll")
    def api_inbox_poll(token: str = "", limit: int = 20) -> dict:
        """拉取新来信（内部运维接口，须审核令牌）：解析回信/退信/退订并入库。"""
        _require_reviewer(token)
        if inbox is None:
            raise HTTPException(status_code=503, detail="IMAP 收件通道未配置（请设置 IMAP_* 环境变量）")
        try:
            mails = inbox.fetch_unseen(limit=limit)
        except InboxError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        stored: list[dict[str, Any]] = []
        unsubscribed: list[str] = []
        for mail in mails:
            record = mail.to_record()
            outcome = inbox_ledger.record(record)
            if not outcome.get("recorded"):
                continue
            stored.append(record)
            # 退订：按发件地址回查匿名标识，置 report_opt_in=False
            if record["stop_requested"] and record["from_addr"]:
                for key in store.find_keys_by_email(record["from_addr"]):
                    profile = _profile_of(key)
                    if profile.get("report_opt_in", True):
                        profile["report_opt_in"] = False
                        store.put(key, profile)
                        unsubscribed.append(key)
        return {
            "fetched": len(mails),
            "stored": len(stored),
            "unsubscribed": unsubscribed,
            "mails": stored,
        }

    @app.get("/api/inbox")
    def api_inbox_list(token: str = "", limit: int = 20) -> dict:
        _require_reviewer(token)
        return {
            "count": inbox_ledger.count(),
            "mails": inbox_ledger.list_recent(limit),
        }

    @app.post("/api/email/confirm")
    def api_email(req: EmailConfirmReq) -> dict:
        if mailer is None:
            raise HTTPException(status_code=503, detail="mailer 未配置")
        return mailer.send_if_confirmed(
            email=req.email,
            subject=req.subject,
            body=req.body,
            decision=req.decision,
            confirm_token=req.confirm_token,
            expected_token=expected_token,
        )

    # ---- 情绪自评 ----
    @app.get("/api/assessment/items")
    def api_assessment_items() -> dict:
        return {
            "items": list(ITEMS),
            "choices": [{"value": k, "label": v} for k, v in CHOICE_LABELS.items()],
            "disclaimer": "自评结果不构成诊断，仅供参考。",
        }

    @app.post("/api/assessment")
    def api_assessment(req: AssessmentReq) -> dict:
        try:
            result = score_assessment(req.answers)
        except AssessmentError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if result["urgent"]:
            review_ledger.open_case(
                thread_id="assessment:" + secrets.token_hex(8),
                risk_level="high",
                basis_level="self-assessment",
                basis_reason="自评结果达「建议尽快寻求专业帮助」区间",
                context_summary="用户自评结果达到需尽快寻求专业帮助的区间",
            )
        return result

    # ---- 隐私：保留期 / 导出 ----
    @app.get("/api/privacy/{profile_key}")
    def api_privacy_get(profile_key: str) -> dict:
        return {
            "retention": privacy_store.get_retention(profile_key),
            "purge": privacy_store.purge_schedule(profile_key),
            "choices": [7, 30, 90],
        }

    @app.post("/api/privacy/{profile_key}/retention")
    def api_privacy_retention(profile_key: str, req: RetentionReq) -> dict:
        try:
            record = privacy_store.set_retention(profile_key, req.days)
        except PrivacyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "retention": record, "purge": privacy_store.purge_schedule(profile_key)}

    @app.get("/api/privacy/{profile_key}/export")
    def api_privacy_export(profile_key: str) -> dict:
        return export_bundle(
            profile_key=profile_key,
            profile=store.get(profile_key),
            messages=_thread_messages(graph, profile_key),
            retention=privacy_store.get_retention(profile_key),
        )

    @app.delete("/api/profile/{profile_key}")
    def api_delete_profile(profile_key: str) -> dict:
        profile_deleted = store.delete(profile_key)
        thread_deleted = _delete_thread(graph, profile_key)
        privacy_store.forget(profile_key)
        return {"ok": True, "profile_deleted": profile_deleted, "thread_deleted": thread_deleted}

    # ---- 人工审核台 ----
    def _require_reviewer(token: str) -> None:
        if not reviewer_token or not token or not secrets.compare_digest(token, reviewer_token):
            raise HTTPException(status_code=403, detail="审核台未授权")

    @app.get("/api/review/pending")
    def api_review_pending(token: str = "") -> dict:
        _require_reviewer(token)
        return {
            "pending": review_ledger.list_pending(),
            "count": review_ledger.count_pending(),
            "decisions": REVIEW_DECISIONS,
            "contact_kinds": CONTACT_KINDS,
        }

    @app.get("/api/review/{ticket_id}")
    def api_review_detail(ticket_id: str, token: str = "") -> dict:
        _require_reviewer(token)
        case = review_ledger.get(ticket_id)
        if case is None:
            raise HTTPException(status_code=404, detail="工单不存在或已闭环")
        thread_id = case.get("thread_id") or ""
        return {
            "case": case,
            "decisions": REVIEW_DECISIONS,
            "contact_kinds": CONTACT_KINDS,
            "context": _context_for_review(_thread_messages(graph, thread_id)),
            "replies": inbox_ledger.by_ticket(ticket_id),
        }

    @app.post("/api/review/decision")
    def api_review_decision(req: ReviewDecisionReq, token: str = "") -> dict:
        _require_reviewer(token)
        ticket_id = req.ticket_id
        if not ticket_id:
            raise HTTPException(status_code=400, detail="缺少 ticket_id")
        case = review_ledger.get(ticket_id)
        if case is None:
            raise HTTPException(status_code=404, detail="工单不存在或已闭环")
        thread_id = case.get("thread_id") or ""
        cfg = {"configurable": {"thread_id": thread_id}}
        # 裁决必须真正驱动图恢复：先确认该 thread 仍停在 human_review 中断点。
        # 否则（会话已被删除 / 已恢复推进）update_state+invoke(None) 不会经过 human_review，
        # 会返回空 audit_log 却报 ok=True，并让台账闭环——值班员会误以为已处理。
        state = _thread_state(graph, thread_id)
        if not state:
            raise HTTPException(
                status_code=409,
                detail="该工单对应的会话已不存在（可能已被用户删除数据），无法恢复；请勿据此闭环",
            )
        if not _awaiting_human_review(graph, thread_id):
            raise HTTPException(
                status_code=409,
                detail="该工单的中断态已失效（会话已恢复或已推进），不能重复裁决",
            )
        try:
            graph.update_state(cfg, {"review_decision": req.decision})
            resumed = graph.invoke(None, cfg)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"图恢复失败：{exc}") from exc
        try:
            record = review_ledger.decide(
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
        return {
            "ok": True,
            "review": record,
            "audit_log": resumed.get("audit_log"),
            "contact_log": resumed.get("contact_log"),
            "next_followup": resumed.get("next_followup"),
            "pending": review_ledger.count_pending(),
        }

    # ---- 申诉与投诉举报 ----
    @app.post("/api/appeal")
    def api_appeal(req: AppealReq) -> dict:
        try:
            record = appeal_store.submit(req.kind, req.text, req.profile_key)
        except AppealError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "ticket_id": record["ticket_id"], "submitted_at": record["submitted_at"]}

    # ---- 转介资源 ----
    @app.get("/api/resources")
    def api_resources() -> dict:
        return {
            "note": RESOURCES_NOTE,
            "entries": RESOURCE_ENTRIES,
            "hotlines": resource_store.approved(),
            "appeals": {"submit_url": "/api/appeal", "kinds": APPEAL_KINDS},
        }

    @app.post("/api/resources/hotline")
    def api_resource_register(req: ResourceRegisterReq, token: str = "") -> dict:
        _require_reviewer(token)
        try:
            record = resource_store.add(
                title=req.title,
                detail=req.detail,
                kind=req.kind,
                tel=req.tel,
                reviewer=req.reviewer,
            )
        except ResourceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "hotline": record}

    return app
