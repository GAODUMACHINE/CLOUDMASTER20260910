"""L2 人工审核台账（计划书 3.2.3 三级危机分级与路由 / 3.3.1 危机干预协议）。

补齐「审核台」缺失的后端：中断态 → 待审队列 → 审核结论写回 → 闭环。
红线与隐私：
- 台账只落「判定依据 + 结论 + 联络动作」，**绝不落对话原文**（数据设计硬约束）；
- 联系方式（监护人/紧急联系人）不落台账，仅记录「已请求联络」这一动作；
- append-only，可审计、不可篡改。
"""

from __future__ import annotations

import json
import os
import secrets
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
    """append-only 人工审核台账（JSONL，`data/private/`，gitignored）。"""

    def __init__(self, path: str | None = None):
        raw = path or os.environ.get("REVIEW_DB_PATH", "")
        self._path = Path(raw) if raw else Path("data/private/reviews.jsonl")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def _read_all(self) -> list[dict[str, Any]]:
        try:
            text = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        records: list[dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:  # 坏行跳过，不阻断审核台
                continue
        return records

    def _append(self, record: dict[str, Any]) -> None:
        with self._lock:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")

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
        existing = self.pending_for_thread(thread_id)
        if existing is not None:
            return existing
        record = {
            "ticket_id": "HR-" + secrets.token_hex(6),
            "thread_id": thread_id,
            "profile_key": profile_key,
            "opened_at": datetime.now(UTC).isoformat(),
            "risk_level": risk_level,
            "basis_level": basis_level,
            "basis_reason": basis_reason[:500],
            # 仅摘要，不含对话原文（隐私硬约束）。
            "context_summary": context_summary[:200],
            "status": "pending",
            "decision": None,
        }
        self._append(record)
        return record

    def pending_for_thread(self, thread_id: str) -> dict[str, Any] | None:
        latest: dict[str, Any] | None = None
        for rec in self._read_all():
            if rec.get("thread_id") != thread_id:
                continue
            if rec.get("status") == "pending":
                latest = rec
            elif latest is not None and rec.get("ticket_id") == latest.get("ticket_id"):
                latest = None  # 已闭环
        return latest

    def _resolved_ids(self) -> set[str]:
        return {
            r.get("ticket_id")
            for r in self._read_all()
            if r.get("status") == "resolved" and r.get("ticket_id")
        }

    def list_pending(self) -> list[dict[str, Any]]:
        """待审队列：status=pending 且尚未被结论行闭环的案件。"""
        resolved = self._resolved_ids()
        out: list[dict[str, Any]] = []
        for rec in self._read_all():
            if rec.get("status") != "pending":
                continue
            if rec.get("ticket_id") in resolved:
                continue
            out.append(rec)
        return out

    def get(self, ticket_id: str) -> dict[str, Any] | None:
        """取未闭环案件；已闭环工单返回 None（审核结论唯一、不可覆写）。"""
        if ticket_id in self._resolved_ids():
            return None
        for rec in self._read_all():
            if rec.get("ticket_id") == ticket_id and rec.get("status") == "pending":
                return rec
        return None

    def is_resolved(self, ticket_id: str) -> bool:
        return ticket_id in self._resolved_ids()

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
        case = self.get(ticket_id)
        if case is None:
            raise ReviewError("工单不存在或已闭环")
        record = {
            "ticket_id": ticket_id,
            "thread_id": case.get("thread_id"),
            "decision": decision,
            "decision_label": REVIEW_DECISIONS[decision],
            "contact_kind": contact_kind,
            "contact_label": CONTACT_KINDS[contact_kind],
            "reviewer": reviewer or "unassigned",
            "resolved_at": datetime.now(UTC).isoformat(),
            "status": "resolved",
        }
        self._append(record)
        return record

    def count_pending(self) -> int:
        return len(self.list_pending())
