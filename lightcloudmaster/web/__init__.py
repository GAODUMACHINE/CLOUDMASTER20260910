"""Web 应用装配：构造默认存储、挂载静态前端与全部 router，端点行为在 routers/。"""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from ..services.mail.imap import ImapInbox
from ..storage.agreements import AgreementStore
from ..storage.appeals import AppealStore
from ..storage.followups import FollowupQueue
from ..storage.inbox import InboxStore
from ..storage.privacy import PrivacyStore
from ..storage.profiles import ProfileStore
from ..storage.reports import ReportRegistry
from ..storage.resources import ResourceStore
from ..storage.reviews import ReviewLedger
from .deps import AppContext
from .routers import appeals as appeals_router
from .routers import assessment as assessment_router
from .routers import chat as chat_router
from .routers import privacy as privacy_router
from .routers import register as register_router
from .routers import report as report_router
from .routers import resources as resources_router
from .routers import review as review_router

# 报告确认令牌的进程盐：草稿（发令牌）与发送（验令牌）须同一把盐，重启即换。
_PROCESS_SALT = secrets.token_hex(16)


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
    app = FastAPI(title="LIGHTCLOUDMASTER", version="2.0.0")
    appeal_store = appeals or AppealStore()
    review_ledger = reviews or ReviewLedger()
    privacy_store = privacy or PrivacyStore()
    resource_store = resources or ResourceStore()
    inbox_ledger = inbox_store or InboxStore()
    report_registry = reports or ReportRegistry()
    agreements = AgreementStore()
    followups = FollowupQueue()
    salt = report_salt or _PROCESS_SALT

    # web/ 比旧入口深一层，静态目录要多上一级到仓库根的 frontend/。
    _frontend = Path(__file__).resolve().parent.parent.parent / "frontend"
    app.mount("/web", StaticFiles(directory=str(_frontend), html=True), name="web")

    @app.get("/", include_in_schema=False)
    def index() -> RedirectResponse:
        return RedirectResponse(url="/web/cloud-glass/")

    app.state.ctx = AppContext(
        graph=graph,
        store=store,
        mailer=mailer,
        review_ledger=review_ledger,
        privacy_store=privacy_store,
        resource_store=resource_store,
        appeal_store=appeal_store,
        inbox_ledger=inbox_ledger,
        report_registry=report_registry,
        inbox=inbox,
        reviewer_token=reviewer_token,
        report_salt=salt,
        agreements=agreements,
        followups=followups,
    )
    app.include_router(register_router.router)
    app.include_router(chat_router.router)
    app.include_router(report_router.router)
    app.include_router(review_router.router)
    app.include_router(assessment_router.router)
    app.include_router(privacy_router.router)
    app.include_router(appeals_router.router)
    app.include_router(resources_router.router)
    return app
