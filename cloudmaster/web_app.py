"""Web 服务（v0.5.0 起，ADR-005；v1.1.0 补匿名 ID 隔离与申诉/退出入口）。
测试一律注入 fake graph/store，禁止触网/真实模型/真实邮件。"""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import service as svc
from .appeals import APPEAL_KINDS, AppealError, AppealStore
from .profile_store import ProfileStore
from .registration import RegistrationError, register


class RegisterReq(BaseModel):
    age: int
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


# 资源页（TC-RES-001 / TC-RES-002）。红线：不硬编码任何真实热线号码，
# 号码须由人工审核后台配置后再展示（未审核号码一律不下发）。
RESOURCES: dict[str, Any] = {
    "note": "本页不提供未经人工审核的热线号码；如遇紧急情况请拨打当地急救电话或就近就医。",
    "entries": [
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
            "detail": (
                "若你有立即伤害自己的想法，请立即拨打当地急救电话或前往就近医院急诊，并联系可信任的人。"
            ),
        },
    ],
    "appeals": {"submit_url": "/api/appeal", "kinds": APPEAL_KINDS},
}


def _delete_thread(graph: Any, thread_id: str) -> bool:
    """删除该匿名 ID 的会话 thread（Checkpointer 数据）。尽力而为：异常不阻断用户退出。"""
    fn = getattr(getattr(graph, "checkpointer", None), "delete_thread", None)
    if fn is None:
        return False
    try:
        fn(thread_id)
    except Exception:  # noqa: BLE001 -- 用户退出优先，后端清理异常不影响退出结果
        return False
    return True


def create_app(
    graph: Any,
    store: ProfileStore,
    mailer: Any = None,
    expected_token: str = "token",
    appeals: AppealStore | None = None,
) -> FastAPI:
    app = FastAPI(title="CLOUDMASTER", version="1.1.0")
    appeal_store = appeals or AppealStore()

    _frontend = Path(__file__).resolve().parent.parent / "frontend"
    app.mount("/web", StaticFiles(directory=str(_frontend), html=True), name="web")

    @app.post("/api/register")
    def api_register(req: RegisterReq) -> dict:
        try:
            profile = register(
                age=req.age,
                guardian_contact_available=req.guardian_contact_available,
                dependency_tendency=req.dependency_tendency,
            )
        except RegistrationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        # 匿名 ID 必须每人唯一且不可预测。旧实现用 hash(age) 推导，会让同龄用户共用同一 thread
        # 并跨进程不稳定（PYTHONHASHSEED 随机），造成串会话与错删数据，故改为随机标识。
        key = "anon-" + secrets.token_urlsafe(12)
        store.put(key, profile)
        return {"ok": True, "profile_key": key}

    @app.post("/api/chat")
    def api_chat(req: ChatReq) -> dict:
        res = svc.service_turn(
            graph, store, req.profile_key, req.text, {"configurable": {"thread_id": req.profile_key}}
        )
        msgs = res.get("messages") or []
        basis = res.get("crisis_basis") or {}
        return {
            "reply": msgs[-1].content if msgs else "",
            "risk_level": res.get("risk_level"),
            "next_agent": res.get("next_agent"),
            "review_decision": res.get("review_decision"),
            "basis_reason": basis.get("reason"),
        }

    @app.post("/api/chat/stream")
    def api_stream(req: ChatReq):
        from fastapi.responses import StreamingResponse

        cfg = {"configurable": {"thread_id": req.profile_key}}
        res = svc.service_turn(graph, store, req.profile_key, req.text, cfg)
        msgs = res.get("messages") or []
        reply = msgs[-1].content if msgs else ""
        return StreamingResponse(iter("data: " + reply + "\n\n"), media_type="text/event-stream")

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

    @app.delete("/api/profile/{profile_key}")
    def api_delete_profile(profile_key: str) -> dict:
        """账户便捷退出/删除（第 19 条，TC-PRIV-004）：清最小画像 + 该 thread 的会话数据。

        幂等且对未知标识同样返回成功，避免通过状态码枚举他人是否已注册（隐私最小化）。
        """
        profile_deleted = store.delete(profile_key)
        thread_deleted = _delete_thread(graph, profile_key)
        return {"ok": True, "profile_deleted": profile_deleted, "thread_deleted": thread_deleted}

    @app.post("/api/appeal")
    def api_appeal(req: AppealReq) -> dict:
        """申诉与投诉举报入口（第 21 条，TC-PRIV-006 / TC-RES-002）。"""
        try:
            record = appeal_store.submit(req.kind, req.text, req.profile_key)
        except AppealError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "ticket_id": record["ticket_id"], "submitted_at": record["submitted_at"]}

    @app.get("/api/resources")
    def api_resources() -> dict:
        return RESOURCES

    return app
