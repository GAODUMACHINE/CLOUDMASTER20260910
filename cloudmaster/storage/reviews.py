"""L2 人工审核台账（v2.0.0 存储层，计划书 3.2.3 三级危机分级与路由 / 3.3.1 危机干预协议）。

对旧 cloudmaster/review_queue.py（JSONL 版）的 1:1 SQLite 移植：类名 / 方法签名 / 异常类型
与中文文案 / 返回 dict 的键与值语义完全一致，调用方零改动切换。设计取舍：
- 两表分工（DDL 见 storage/db.py）：review_cases 承载生命周期（status 单列翻转），
  review_decisions 承载闭环结论明细（append-only）。旧实现靠「追加 resolved 行 + 读侧过滤
  已闭环 ticket」表达闭环；新模型把「翻状态 + 写结论」放进**同一事务**原子完成，读侧无需
  去重，也不存在「pending 行已被结论行闭环」的中间态。
- 同一 thread 未决唯一：进程内靠共享连接锁串行；跨进程双登记由部分唯一索引
  uq_review_pending_thread 在数据库层拦截，open_case 捕获 IntegrityError 后回滚重查、
  返回既有案件——与旧实现「不重复登记、返回既有案件」语义一致。
- 返回 dict 与旧 JSONL 记录同形：保留恒为 None 的 decision 键；不外泄 v2.0.0 新增的
  source 列（该列供 P4 评估链路使用，暂不进入旧契约形态）。
- 读方法同样持锁：每个数据库文件进程内仅一连接（check_same_thread=False），跨线程共用
  同一连接的游标必须串行。
- 红线不变：台账只落判定依据（截 500）与摘要（截 200），**绝不落对话原文**；联系方式
  （监护人/紧急联系人）不落台账，仅记录「已请求联络」这一动作。

常量（选项表/词表）与异常类自旧模块原样复制，保持本模块自包含；旧模块 P3 才删，暂允许重复。
"""

from __future__ import annotations

import secrets
import sqlite3
from pathlib import Path
from typing import Any

from . import db

REVIEW_DECISIONS = {
    "approve": "继续对话并执行联络（监护人/紧急联系人）",
    "block": "仅审计留痕，不发起联络",
}

# 审核台可选的联络对象（计划书 3.2.4：监护人/紧急联系人，仅未成年人必填、访问需授权）。
CONTACT_KINDS = {
    "guardian": "监护人",
    "emergency": "紧急联系人",
    "school": "学校学工/心理中心",
    "none": "不发起联络",
}

LEDGER_SCHEMA_REQUIRED = ("ticket_id", "thread_id", "decision")


class ReviewError(ValueError):
    pass


class ReviewLedger:
    """append-only 人工审核台账（SQLite business.db，经 storage.db 共享连接与锁）。"""

    def __init__(self, path: str | None = None):
        self._path = db.resolve_db_path(path, "REVIEW_DB_PATH")
        # 与旧实现一致：父目录不存在则先建（生产缺省 data/private/）。
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn, self._lock = db.connect(self._path)

    @property
    def path(self) -> Path:
        return self._path

    @staticmethod
    def _case_of_row(row: sqlite3.Row) -> dict[str, Any]:
        """review_cases 行 → 旧 JSONL 开案记录同形 dict（decision 恒 None，source 列不外泄）。"""
        return {
            "ticket_id": row["ticket_id"],
            "thread_id": row["thread_id"],
            "profile_key": row["profile_key"],
            "opened_at": row["opened_at"],
            "risk_level": row["risk_level"],
            "basis_level": row["basis_level"],
            "basis_reason": row["basis_reason"],
            "context_summary": row["context_summary"],
            "status": row["status"],
            "decision": None,
        }

    def open_case(
        self,
        *,
        thread_id: str,
        risk_level: str,
        basis_level: str = "",
        basis_reason: str = "",
        profile_key: str = "",
        context_summary: str = "",
    ) -> dict[str, Any]:
        """登记待审案件。同一 thread 已有未决案件时不重复登记（返回既有案件）。"""
        record = {
            "ticket_id": "HR-" + secrets.token_hex(6),
            "thread_id": thread_id,
            "profile_key": profile_key,
            "opened_at": db.now_iso(),
            "risk_level": risk_level,
            "basis_level": basis_level,
            "basis_reason": basis_reason[:500],
            # 仅摘要，不含对话原文（隐私硬约束）。
            "context_summary": context_summary[:200],
            "status": "pending",
            "decision": None,
        }
        with self._lock:
            existing = self.pending_for_thread(thread_id)
            if existing is not None:
                return existing
            try:
                self._conn.execute(
                    "INSERT INTO review_cases"
                    " (ticket_id, thread_id, profile_key, opened_at, risk_level,"
                    " basis_level, basis_reason, context_summary, status)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        record["ticket_id"],
                        thread_id,
                        profile_key,
                        record["opened_at"],
                        risk_level,
                        basis_level,
                        record["basis_reason"],
                        record["context_summary"],
                        "pending",
                    ),
                )
                self._conn.commit()
            except sqlite3.IntegrityError:
                # 并发撞 uq_review_pending_thread（跨进程双登记）：回滚本记录，重查返回既有。
                self._conn.rollback()
                existing = self.pending_for_thread(thread_id)
                if existing is not None:
                    return existing
                raise
        return record

    def pending_for_thread(self, thread_id: str) -> dict[str, Any] | None:
        """取该 thread 的未决案件；无或已闭环返回 None（唯一索引保证至多一行）。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT ticket_id, thread_id, profile_key, opened_at, risk_level, basis_level,"
                " basis_reason, context_summary, status"
                " FROM review_cases WHERE thread_id = ? AND status = 'pending'",
                (thread_id,),
            ).fetchone()
        return self._case_of_row(row) if row is not None else None

    def list_pending(self) -> list[dict[str, Any]]:
        """待审队列：status=pending 的案件，按开案时间（再按 ticket_id）稳定排序。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT ticket_id, thread_id, profile_key, opened_at, risk_level, basis_level,"
                " basis_reason, context_summary, status"
                " FROM review_cases WHERE status = 'pending' ORDER BY opened_at, ticket_id"
            ).fetchall()
        return [self._case_of_row(row) for row in rows]

    def get(self, ticket_id: str) -> dict[str, Any] | None:
        """取未闭环案件；已闭环工单返回 None（审核结论唯一、不可覆写）。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT ticket_id, thread_id, profile_key, opened_at, risk_level, basis_level,"
                " basis_reason, context_summary, status"
                " FROM review_cases WHERE ticket_id = ? AND status = 'pending'",
                (ticket_id,),
            ).fetchone()
        return self._case_of_row(row) if row is not None else None

    def is_resolved(self, ticket_id: str) -> bool:
        """工单是否已闭环（以 review_decisions 存在结论记录为准）。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT EXISTS(SELECT 1 FROM review_decisions WHERE ticket_id = ?)",
                (ticket_id,),
            ).fetchone()
        return bool(row[0])

    def decide(
        self,
        ticket_id: str,
        decision: str,
        reviewer: str = "",
        contact_kind: str = "guardian",
    ) -> dict[str, Any]:
        """写回审核结论（闭环）。重复裁决同一工单报错，保证结论唯一。"""
        if decision not in REVIEW_DECISIONS:
            raise ReviewError(f"不支持的审核结论: {decision}")
        if contact_kind not in CONTACT_KINDS:
            raise ReviewError(f"不支持的联络对象: {contact_kind}")
        reviewer_name = reviewer or "unassigned"
        resolved_at = db.now_iso()
        with self._lock:
            # 原子闭环：UPDATE 只命中唯一 pending 行，rowcount 即并发安全的存在性校验。
            cur = self._conn.execute(
                "UPDATE review_cases SET status = 'resolved' WHERE ticket_id = ? AND status = 'pending'",
                (ticket_id,),
            )
            if cur.rowcount != 1:
                self._conn.rollback()
                raise ReviewError("工单不存在或已闭环")
            row = self._conn.execute(
                "SELECT thread_id FROM review_cases WHERE ticket_id = ?", (ticket_id,)
            ).fetchone()
            if row is None:  # rowcount==1 后必然存在，防御性兜底
                self._conn.rollback()
                raise ReviewError("工单不存在或已闭环")
            thread_id = row["thread_id"]
            self._conn.execute(
                "INSERT INTO review_decisions"
                " (ticket_id, thread_id, decision, decision_label, contact_kind,"
                " contact_label, reviewer, resolved_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ticket_id,
                    thread_id,
                    decision,
                    REVIEW_DECISIONS[decision],
                    contact_kind,
                    CONTACT_KINDS[contact_kind],
                    reviewer_name,
                    resolved_at,
                ),
            )
            self._conn.commit()
        return {
            "ticket_id": ticket_id,
            "thread_id": thread_id,
            "decision": decision,
            "decision_label": REVIEW_DECISIONS[decision],
            "contact_kind": contact_kind,
            "contact_label": CONTACT_KINDS[contact_kind],
            "reviewer": reviewer_name,
            "resolved_at": resolved_at,
            "status": "resolved",
        }

    def count_pending(self) -> int:
        """当前待审数量（闭环即翻状态，COUNT pending 即队列长度）。"""
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM review_cases WHERE status = 'pending'").fetchone()
        return int(row[0])
