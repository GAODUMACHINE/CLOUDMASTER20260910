"""生产入口：本机运行（真实 LLM + 持久化 + Web 托管，云朵玻璃前端位于 /web）。

密钥/主机/模型全部经 .env 或环境注入（gitignored，绝不硬编码入库）。
测试请勿导入本模块（会在导入时构造真实 LLM）；测试一律注入 fake LLM。
"""

from __future__ import annotations

from .graph import build_graph
from .mailer import Mailer
from .model import create_llm
from .persistence import build_checkpointer
from .profile_store import ProfileStore
from .web_app import create_app


def build_app():
    """组装完整应用：真实图 + 持久化 checkpointer/store + 邮件桩 + Web。"""
    graph = build_graph(create_llm(), checkpointer=build_checkpointer())
    store = ProfileStore()
    return create_app(graph, store, Mailer())


app = build_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("cloudmaster.server:app", host="127.0.0.1", port=8000, reload=False)
