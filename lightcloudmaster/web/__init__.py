"""Web 应用装配（v2.0.0 P3，计划 §21 / ADR-011 §1）：web_app 单文件 660 行 → web/ 包按域拆分。

本模块只做装配：构造默认存储（统一 SQLite 底座，ADR-012）、解析前端静态目录、
把全部协作者装进 AppContext（app.state.ctx）、挂载 8 个 router。端点行为在
routers/，鉴权与图辅助在 deps.py，SSE 在 sse.py，请求模型在 schemas.py。

- create_app 参数名与旧签名逐字一致：既有调用方（server.py）与 246 例测试零改动；
  expected_token 已无消费者——v2.0.0 P3 删除 /api/email/confirm（处置表 #12：以 body
  传完整收件人/主题/正文、仅凭单一静态令牌放行，等于开放中继；前端零调用）后保留
  该参数仅为签名兼容。
- 新增依赖 agreements（协议签署留痕）/ followups（次日回访队列）默认构造，测试可
  经 AppContext 注入替身。
- 报告确认令牌的进程盐：未注入 report_salt 时在装配处生成一次并贯穿 AppContext——
  草稿（发令牌）与发送（验令牌）必须同一把盐，跨进程不可复用（用户须当次确认）。

红线：测试一律注入 fake graph/store/mailer；本模块绝不 import server（生产装配），
绝不触网。静态目录解析为仓库根 frontend/（web/ 比旧 web_app.py 深一层，多上一级）。
"""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

# router 模块一律带 _router 后缀：create_app 的 appeals/privacy/resources 参数名
# 与同名模块冲突（F811 重定义），别名也让 include 处的语义更直观。
from ..inbox import ImapInbox
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

# 进程级随机盐：同进程内草稿与发送共享，重启即换（令牌不可跨进程复用）。
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
    """组装 FastAPI 应用（行为契约见各 router 模块 docstring）。

    expected_token：已无消费者，保留仅为签名兼容（防调用方炸），见模块 docstring。
    """
    app = FastAPI(title="LIGHTCLOUDMASTER", version="2.0.0")
    # 默认全部走统一存储层（ADR-012）：未显式注入即落 business.db（缺省 data/private/，
    # gitignored）；测试经 conftest 的 *_DB_PATH / BUSINESS_DB_PATH 隔离到 tmp_path。
    appeal_store = appeals or AppealStore()
    review_ledger = reviews or ReviewLedger()
    privacy_store = privacy or PrivacyStore()
    resource_store = resources or ResourceStore()
    inbox_ledger = inbox_store or InboxStore()
    report_registry = reports or ReportRegistry()
    agreements = AgreementStore()
    followups = FollowupQueue()
    salt = report_salt or _PROCESS_SALT

    # web/ 在包内深一层（lightcloudmaster/web/），静态目录须多上一级到仓库根的 frontend/。
    _frontend = Path(__file__).resolve().parent.parent.parent / "frontend"
    app.mount("/web", StaticFiles(directory=str(_frontend), html=True), name="web")

    @app.get("/", include_in_schema=False)
    def index() -> RedirectResponse:
        """根路径直接进用户前端。

        此前 `/` 与 `/web/` 都是 404，必须一字不差地输入 `/web/cloud-glass/` 才能进入，
        很容易被误判成「前端坏了/进不去」。统一由根路径跳转（`/web/` 由 frontend/index.html 承接）。
        """
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
