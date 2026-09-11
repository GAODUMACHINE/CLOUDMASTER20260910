"""生产入口：本机运行（真实 LLM + 持久化 + Web 托管，云朵玻璃前端位于 /web）。

密钥/主机/模型全部经 .env 或环境注入（gitignored，绝不硬编码入库）。
测试请勿导入本模块（会在导入时构造真实 LLM）；测试一律注入 fake LLM。
"""

from __future__ import annotations

from .config import settings
from .graph import build_graph
from .mailer import Mailer
from .model import create_llm, create_stub_llm
from .persistence import build_checkpointer
from .profile_store import ProfileStore
from .web_app import create_app


def build_app():
    """组装完整应用：图 + 持久化 checkpointer/store + 邮件桩 + Web。

    模型选择：settings.cm_stub（CM_STUB=1）→ 本地确定性 StubLLM（零额度/不触网，先跑通全流程）；
    否则 → 真实 Qwen（需该模型已由工作空间对当前 key 授权）。"""
    llm = create_stub_llm() if settings.cm_stub else create_llm()
    graph = build_graph(llm, checkpointer=build_checkpointer())
    store = ProfileStore()
    return create_app(graph, store, Mailer())


app = build_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("cloudmaster.server:app", host="127.0.0.1", port=8000, reload=False)
