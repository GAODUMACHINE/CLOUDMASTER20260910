"""持久化 Checkpointer（v0.2.0，ADR-002）。SQLite 文件落盘，跨刷新/跨天接续。
路径经环境变量注入，禁止绝对路径硬编码；测试一律用 tmp_path。"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver


def _resolve(p: str | None, env_name: str, default: str) -> Path:
    raw = p or os.environ.get(env_name, "")
    path = Path(raw) if raw else Path(default)
    path.parent.mkdir(parents=True, exist_ok=True)  # data/private 等相对目录
    return path


def build_checkpointer(db_path: str | None = None) -> SqliteSaver:
    """构造文件后备 SqliteSaver。db_path 缺省取 MEMORY_DB_PATH || data/private/lightcloudmaster.sqlite3。"""
    path = _resolve(db_path, "MEMORY_DB_PATH", "data/private/lightcloudmaster.sqlite3")
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return SqliteSaver(conn)
