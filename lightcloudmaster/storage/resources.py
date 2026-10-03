"""已审核转介资源 DAL（TC-RES-001）——SQLite 版。

红线不变：**不硬编码任何真实热线号码**。默认返回空列表；只有经人工审核后台录入
（须令牌 + 审核人署名）的号码才会下发给前端，未审核号码一律不下发。

设计取舍（v2.0.0 存储层 P1）：
- 公开 API 与旧 lightcloudmaster/resources.py 完全一致：类名 / 方法签名 / ResourceError
  与中文错误文案（逐字）/ 返回 dict 的键序与语义，调用方零改动切换；
  RESOURCE_KINDS 与 _TEL_RE 复制进本模块使其自包含（旧模块 P3 才删，暂时允许重复）。
- db.py §16 的 13 表清单未列转介资源：它是人工审核录入的**下发清单**，无匿名键/
  工单语义、不参与保留期治理，与业务台账不同类。表 DDL 已补入 db.py 集中 DDL
  （connect() 即建全表），本模块不再自带建表语句。
- 顺序语义：旧 JSONL 逐行读 = 插入序，此处以 ORDER BY rowid 等价保持。
- approved() 的 `WHERE title != '' AND reviewer != ''` 与旧
  `r.get("title") and r.get("reviewer")` 过滤语义一致——add() 校验之外再由数据库层
  兜底，防绕过校验直写的行混入下发。
- 返回 dict 键序 {title, detail, kind, kind_label, tel, reviewer, approved_at} 与旧
  记录一致；内部自增 id 不外泄。SQL 一律 ? 参数化；写方法 with self._lock: 执行 +
  conn.commit()；时间戳一律 db.now_iso()；本模块无布尔列。
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
        # 与旧 store 一致：初始化即确保父目录存在（缺省 data/private 可能尚未创建），
        # 再取进程级共享连接与锁（建表由 db.connect 统一幂等完成）。
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
