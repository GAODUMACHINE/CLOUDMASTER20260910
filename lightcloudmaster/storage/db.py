"""统一 SQLite 存储底座。

- 业务库 business.db 与 LangGraph checkpoint 库分文件：schema 所有权、备份/迁移
  节奏、保留期治理皆不同，互不干扰。
- 连接模型：每个数据库文件每进程一连接（check_same_thread=False）+ 每连接一把
  RLock 串行化——与 SqliteSaver 同构；PRAGMA WAL + busy_timeout=5000 +
  foreign_keys=ON。因此生产只能跑单 worker。
- 除 checkpoint 外一切业务持久化经本包；services/web 不直接开文件。
- 路径收口：全部 DAL 经 resolve_db_path() 解析（显式参数 → 各自环境变量 →
  BUSINESS_DB_PATH → data/private/business.db）。
- audit_events 为 append-only：触发器在库级禁止 UPDATE/DELETE。
- review_cases 部分唯一索引 UNIQUE(thread_id) WHERE status='pending'：
  同一 thread 未闭环不重复开案，跨进程双登记也被数据库层拦截。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_BUSINESS_DB = "data/private/business.db"

DDL = """
CREATE TABLE IF NOT EXISTS profiles (
  anon_key TEXT PRIMARY KEY,
  age INTEGER,
  is_minor INTEGER,
  guardian_contact_available INTEGER,
  emergency_contact_available INTEGER,
  dependency_tendency INTEGER,
  email TEXT,
  report_opt_in INTEGER,
  data_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_profiles_email ON profiles(email);

CREATE TABLE IF NOT EXISTS privacy_settings (
  anon_key TEXT PRIMARY KEY,
  retention_days INTEGER NOT NULL CHECK (retention_days IN (7, 30, 90)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agreements (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  anon_key TEXT NOT NULL,
  version TEXT NOT NULL,
  signed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agreements_key ON agreements(anon_key);

CREATE TABLE IF NOT EXISTS review_cases (
  ticket_id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL,
  profile_key TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT 'chat' CHECK (source IN ('chat', 'assessment')),
  opened_at TEXT NOT NULL,
  risk_level TEXT NOT NULL,
  basis_level TEXT NOT NULL DEFAULT '',
  basis_reason TEXT NOT NULL DEFAULT '',
  context_summary TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'resolved'))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_review_pending_thread
  ON review_cases(thread_id) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_review_cases_status ON review_cases(status);

CREATE TABLE IF NOT EXISTS review_decisions (
  ticket_id TEXT PRIMARY KEY REFERENCES review_cases(ticket_id),
  thread_id TEXT NOT NULL,
  decision TEXT NOT NULL CHECK (decision IN ('approve', 'block')),
  decision_label TEXT NOT NULL,
  contact_kind TEXT NOT NULL,
  contact_label TEXT NOT NULL,
  reviewer TEXT NOT NULL,
  resolved_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS appeals (
  ticket_id TEXT PRIMARY KEY,
  submitted_at TEXT NOT NULL,
  kind TEXT NOT NULL,
  kind_label TEXT NOT NULL,
  text TEXT NOT NULL,
  profile_key TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'received'
);

CREATE TABLE IF NOT EXISTS appeal_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticket_id TEXT NOT NULL REFERENCES appeals(ticket_id),
  action TEXT NOT NULL,
  actor TEXT NOT NULL DEFAULT '',
  note TEXT NOT NULL DEFAULT '',
  acted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_appeal_events_ticket ON appeal_events(ticket_id);

CREATE TABLE IF NOT EXISTS inbox_mails (
  uid TEXT PRIMARY KEY,
  kind TEXT NOT NULL DEFAULT 'other',
  from_addr TEXT NOT NULL DEFAULT '',
  subject TEXT NOT NULL DEFAULT '',
  date TEXT NOT NULL DEFAULT '',
  ticket TEXT NOT NULL DEFAULT '',
  body TEXT NOT NULL DEFAULT '',
  stop_requested INTEGER NOT NULL DEFAULT 0,
  fetched_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_inbox_mails_ticket ON inbox_mails(ticket);

CREATE TABLE IF NOT EXISTS report_drafts (
  report_id TEXT PRIMARY KEY,
  profile_key TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  content_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS report_sents (
  report_id TEXT PRIMARY KEY,
  profile_key TEXT NOT NULL DEFAULT '',
  to_addr TEXT NOT NULL DEFAULT '',
  subject TEXT NOT NULL DEFAULT '',
  sent_at TEXT NOT NULL,
  message_id TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_report_sents_profile ON report_sents(profile_key);

CREATE TABLE IF NOT EXISTS mail_sent_ledger (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  to_addr TEXT NOT NULL,
  subject TEXT NOT NULL,
  sent_at TEXT NOT NULL,
  message_id TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS audit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  anon_key TEXT NOT NULL DEFAULT '',
  detail_json TEXT NOT NULL DEFAULT '{}',
  at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS audit_events_no_update
  BEFORE UPDATE ON audit_events
  BEGIN SELECT RAISE(ABORT, 'audit_events 为 append-only 台账，禁止修改'); END;
CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
  BEFORE DELETE ON audit_events
  BEGIN SELECT RAISE(ABORT, 'audit_events 为 append-only 台账，禁止删除'); END;

CREATE TABLE IF NOT EXISTS followups (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticket_id TEXT NOT NULL DEFAULT '',
  anon_key TEXT NOT NULL DEFAULT '',
  scheduled_at TEXT NOT NULL,
  kind TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'done', 'skipped'))
);
CREATE INDEX IF NOT EXISTS idx_followups_status ON followups(status);

CREATE TABLE IF NOT EXISTS resources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL DEFAULT 'school',
  kind_label TEXT NOT NULL DEFAULT '',
  tel TEXT NOT NULL DEFAULT '',
  reviewer TEXT NOT NULL DEFAULT '',
  approved_at TEXT NOT NULL
);
"""

# 每个数据库文件：一个连接 + 一把锁（进程内串行化；跨进程靠 WAL + busy_timeout）。
_CONNECTIONS: dict[str, tuple[sqlite3.Connection, threading.RLock]] = {}
_REGISTRY_LOCK = threading.Lock()


def resolve_db_path(explicit: str | None, env_name: str) -> Path:
    """显式参数 → 专属环境变量 → BUSINESS_DB_PATH → 缺省。

    生产不设任何变量时全部 store 汇入同一 business.db（统一存储）。
    """
    raw = explicit or os.environ.get(env_name, "") or os.environ.get("BUSINESS_DB_PATH", "")
    path = Path(raw) if raw else Path(DEFAULT_BUSINESS_DB)
    return path


def connect(path: str | Path) -> tuple[sqlite3.Connection, threading.RLock]:
    """取（或建）该数据库文件的进程级连接与锁，并确保 DDL 已初始化。"""
    key = str(Path(path).resolve())
    with _REGISTRY_LOCK:
        entry = _CONNECTIONS.get(key)
        if entry is None:
            conn = sqlite3.connect(key, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA foreign_keys=ON")
            lock = threading.RLock()
            with lock:  # 注册前独占：DDL 初始化不与其他线程交错
                conn.executescript(DDL)
                conn.commit()
            entry = (conn, lock)
            _CONNECTIONS[key] = entry
        return entry


def close_all() -> None:
    """关闭全部缓存连接（生产进程退出即释放）。"""
    with _REGISTRY_LOCK:
        for conn, _lock in _CONNECTIONS.values():
            try:
                conn.close()
            except sqlite3.Error:  # noqa: BLE001 -- 清理尽力而为
                pass
        _CONNECTIONS.clear()


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def record_audit(
    conn: sqlite3.Connection,
    lock: threading.RLock,
    kind: str,
    anon_key: str = "",
    detail: dict[str, Any] | None = None,
) -> None:
    """追加一条审计事件（append-only，触发器兜底禁改禁删）。

    kind 取值：retention_changed / data_exported / data_deleted / purge_executed 等。
    """
    with lock:
        conn.execute(
            "INSERT INTO audit_events (kind, anon_key, detail_json, at) VALUES (?, ?, ?, ?)",
            (kind, anon_key, json.dumps(detail or {}, ensure_ascii=False), now_iso()),
        )
        conn.commit()
