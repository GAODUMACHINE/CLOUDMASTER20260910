"""已审核转介资源 DAL。

红线：**不硬编码任何真实热线号码**。默认返回空列表；只有经人工审核录入
（须令牌 + 审核人署名）的号码才会下发给前端。approved() 的 WHERE 过滤在 add()
校验之外由数据库层兜底，防绕过校验直写的行混入下发。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import db

RESOURCE_KINDS = {
    "school": "学校心理健康教育与咨询中心",
    "hospital": "医院心理科/精神卫生中心",
    "hotline": "心理援助热线",
    "emergency": "紧急救助",
    "other": "其他转介资源",
}

# 宽松格式校验：允许数字、空格、连字符、括号与可选区号；拒绝一切非号码字符。
_TEL_RE = re.compile(r"^[0-9][0-9\-\s()]{2,24}$")


class ResourceError(ValueError):
    pass


class ResourceStore:
    """人工审核后的转介资源台账（business.db 内 resources 表）。"""

    def __init__(self, path: str | None = None):
        self._path = db.resolve_db_path(path, "RESOURCE_DB_PATH")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn, self._lock = db.connect(self._path)

    @property
    def path(self) -> Path:
        return self._path

    def add(
        self,
        *,
        title: str,
        detail: str = "",
        kind: str = "school",
        tel: str = "",
        reviewer: str = "",
    ) -> dict[str, Any]:
        """录入一条已审核资源。title 与 reviewer 必填（无审核人签名不许下发）。"""
        name = (title or "").strip()
        if not name:
            raise ResourceError("资源名称不能为空")
        if not (reviewer or "").strip():
            raise ResourceError("必须记录审核人署名（未经人工审核的资源不下发）")
        if kind not in RESOURCE_KINDS:
            raise ResourceError(f"不支持的资源类型: {kind}")
        number = (tel or "").strip()
        if number and not _TEL_RE.match(number):
            raise ResourceError("号码格式不合法")
        record = {
            "title": name,
            "detail": (detail or "").strip()[:300],
            "kind": kind,
            "kind_label": RESOURCE_KINDS[kind],
            "tel": number,
            "reviewer": reviewer.strip(),
            "approved_at": db.now_iso(),
        }
        with self._lock:
            self._conn.execute(
                "INSERT INTO resources (title, detail, kind, kind_label, tel, reviewer,"
                " approved_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    record["title"],
                    record["detail"],
                    record["kind"],
                    record["kind_label"],
                    record["tel"],
                    record["reviewer"],
                    record["approved_at"],
                ),
            )
            self._conn.commit()
        return record

    def approved(self) -> list[dict[str, Any]]:
        """已审核资源（默认空：未录入任何号码即不下发任何号码）。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT title, detail, kind, kind_label, tel, reviewer, approved_at"
                " FROM resources WHERE title != '' AND reviewer != '' ORDER BY rowid"
            ).fetchall()
        return [dict(row) for row in rows]
