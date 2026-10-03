"""报告草稿与发送记录 DAL（v2.0.0 存储层）：report_drafts / report_sents 两表。

设计取舍（对照 lightcloudmaster/mail_store.py::ReportRegistry，公开 API 1:1、调用方零改动）：
- 旧版是纯内存 dict（进程重启即失、实例间不共享）；本 DAL 落 business.db——草稿生命周期
  从"进程级"变为"库级"，对外 API 语义不变（能力增强，非破坏性变更）。
- 草稿以 content_json = json.dumps(draft, ensure_ascii=False) 整体保存，get_draft 返回
  json.loads 的精确副本：报告模板字段演进无需改表结构。
- 发送记录只存交付元数据、不落正文（ADR-009）；返回键形与旧一致——收件地址键名是
  "to" 而非 "to_addr"（web 前端已按 "to" 消费）。
- report_sents.profile_key 取自 report_drafts 同 report_id 行（无草稿行则 ''）：
  v2.0.0 P3 起 sent_records(profile_key) 据此过滤，修复 report/status 跨用户泄漏。
- mark_sent 用 UPSERT（ON CONFLICT DO UPDATE）：同 report_id 重发覆盖旧记录且不改变
  插入序——对齐旧 dict 赋值"更新值不移动键位置"的语义。
- MailStoreError 统一从 storage.inbox 导入（v2.0.0 收口：过渡期两 DAL 各持同名异类，
  会让 `pytest.raises(MailStoreError)` 按导入路径接不住 reports 侧抛出——单一类身份，
  文案不变）。
"""

from __future__ import annotations

import json
from typing import Any

from . import db
from .inbox import MailStoreError

__all__ = ["MailStoreError", "ReportRegistry"]


class ReportRegistry:
    """报告草稿与发送记录（原进程内存版，v2.0.0 起落 business.db）。"""

    def __init__(self, path: str | None = None):
        # 旧版无路径参数（纯内存）；保留零参构造兼容。路径收口：显式参数 →
        # REPORT_DB_PATH → BUSINESS_DB_PATH → data/private/business.db（生产不设变量时
        # 与其余 DAL 汇入统一业务库）。
        self._path = db.resolve_db_path(path, "REPORT_DB_PATH")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn, self._lock = db.connect(self._path)

    def put_draft(self, draft: dict[str, Any]) -> dict[str, Any]:
        """保存报告草稿：content_json 存精确 dict（未知字段一并保留）。"""
        rid = str(draft.get("report_id") or "").strip()
        if not rid:
            raise MailStoreError("报告缺少 report_id")
        content_json = json.dumps(draft, ensure_ascii=False)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO report_drafts"
                " (report_id, profile_key, created_at, content_json) VALUES (?, ?, ?, ?)",
                (rid, str(draft.get("profile_key") or ""), db.now_iso(), content_json),
            )
            self._conn.commit()
        return json.loads(content_json)

    def get_draft(self, report_id: str) -> dict[str, Any] | None:
        """取草稿：返回存储内容的精确副本；不存在返回 None。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT content_json FROM report_drafts WHERE report_id = ?",
                (report_id,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["content_json"])

    def mark_sent(self, report_id: str, delivery: dict[str, Any]) -> dict[str, Any]:
        """登记发送结果（不落正文）；profile_key 回查草稿行，为 P3 过滤预置。"""
        record = {
            "report_id": report_id,
            "to": delivery.get("to", ""),
            "subject": delivery.get("subject", ""),
            "sent_at": delivery.get("sent_at") or db.now_iso(),
            "message_id": delivery.get("message_id", ""),
        }
        with self._lock:
            draft = self._conn.execute(
                "SELECT profile_key FROM report_drafts WHERE report_id = ?",
                (report_id,),
            ).fetchone()
            profile_key = draft["profile_key"] if draft else ""
            self._conn.execute(
                "INSERT INTO report_sents"
                " (report_id, profile_key, to_addr, subject, sent_at, message_id)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(report_id) DO UPDATE SET"
                " profile_key=excluded.profile_key, to_addr=excluded.to_addr,"
                " subject=excluded.subject, sent_at=excluded.sent_at,"
                " message_id=excluded.message_id",
                (
                    report_id,
                    profile_key,
                    record["to"],
                    record["subject"],
                    record["sent_at"],
                    record["message_id"],
                ),
            )
            self._conn.commit()
        return record

    def sent_records(self, profile_key: str | None = None) -> list[dict[str, Any]]:
        """发送记录，按插入序。profile_key 缺省返回全量（运维视角）；传入则只回本人记录
        ——v2.0.0 P3 起 report/status 以本人 key 调用，修复跨用户泄漏（任一请求者
        曾能看到全部人的发送记录）。"""
        query = "SELECT report_id, to_addr, subject, sent_at, message_id FROM report_sents"
        params: tuple[Any, ...] = ()
        if profile_key is not None:
            query += " WHERE profile_key = ?"
            params = (profile_key,)
        query += " ORDER BY rowid"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [
            {
                "report_id": r["report_id"],
                "to": r["to_addr"],
                "subject": r["subject"],
                "sent_at": r["sent_at"],
                "message_id": r["message_id"],
            }
            for r in rows
        ]

    def delete_for_profile(self, profile_key: str) -> int:
        """清除该匿名标识的全部报告草稿与发送台账（保留期治理用，jobs/purge 调用）。

        先删 sents 再删 drafts（外键无约束，顺序只为日志可读）；返回发送记录删除行数。
        草稿含聚合结论（无对话原文，ADR-009 红线），保留期到点即随画像一并清除。
        """
        with self._lock:
            cur = self._conn.execute("DELETE FROM report_sents WHERE profile_key = ?", (profile_key,))
            sent_deleted = cur.rowcount
            self._conn.execute("DELETE FROM report_drafts WHERE profile_key = ?", (profile_key,))
            self._conn.commit()
        return int(sent_deleted)

    def is_sent(self, report_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT EXISTS(SELECT 1 FROM report_sents WHERE report_id = ?)",
                (report_id,),
            ).fetchone()
        return bool(row[0])
