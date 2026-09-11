"""Web 服务（v0.5.0，ADR-005）。测试一律注入 fake graph/store，禁止触网/真实模型/真实邮件。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import service as svc
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


def create_app(graph: Any, store: ProfileStore, mailer: Any = None, expected_token: str = "token") -> FastAPI:
    app = FastAPI(title="CLOUDMASTER", version="0.5.0")

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
        key = "anon-" + str(abs(hash(str(req.age))))
        store.put(key, profile)
        return {"ok": True, "profile_key": key}

    @app.post("/api/chat")
    def api_chat(req: ChatReq) -> dict:
        res = svc.service_turn(
            graph, store, req.profile_key, req.text, {"configurable": {"thread_id": req.profile_key}}
        )
        msgs = res.get("messages") or []
        return {
            "reply": msgs[-1].content if msgs else "",
            "risk_level": res.get("risk_level"),
            "next_agent": res.get("next_agent"),
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

    return app
