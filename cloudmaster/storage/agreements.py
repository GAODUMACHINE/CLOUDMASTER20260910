"""注册协议签署留痕 DAL（v2.0.0 P4，《办法》第 12 条 / TC-REG-007）：agreements 表。

设计取舍（ADR-011 §1 / ADR-005）：
- 用户完成注册即视为签署当版服务协议：落一条 (匿名键, 版本, 时间) 记录，满足
  「记录含协议版本、签署时间、用户 ID，不可篡改、可审计」的验收要求——append-only
  只增不改（无 UPDATE/DELETE 路径），配合统一库的审计触发器体系即不可篡改。
- 零额外隐私：只存匿名键 + 版本 + 时间，不存任何身份字段；协议版本常量
  AGREEMENT_VERSION 集中在此，协议文本升级只改这一处。
- 惰性注册：注册服务（services.registration.register_profile）三步写的第三步，
  失败不回滚画像（匿名 ID 未返回用户即废键，无隐私后果，见服务层 docstring 取舍）。
- 约定与其余 DAL 一致：SQL 一律 ? 参数化、写方法 with self._lock + commit()、
  时间戳 db.now_iso()、路径经 resolve_db_path 收口。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import db

# 当前服务协议版本（注册即签署留痕的版本号；协议文本变更时只改这里）。
AGREEMENT_VERSION = "v2.0.0"


class AgreementStore:
    """协议签署台账（append-only；统一业务库 agreements 表）。"""

    def __init__(self, path: str | None = None):
        self._path: Path = db.resolve_db_path(path, "AGREEMENT_DB_PATH")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn, self._lock = db.connect(self._path)

    @property
    def path(self) -> Path:
        return self._path

    def sign(
        self, anon_key: str, version: str = AGREEMENT_VERSION, *, now: str | None = None
    ) -> dict[str, Any]:
        """记录一次签署（同一键可多次签署——版本升级后重签是正常轨迹）。"""
        signed_at = now or db.now_iso()
        with self._lock:
            self._conn.execute(
                "INSERT INTO agreements (anon_key, version, signed_at) VALUES (?, ?, ?)",
                (anon_key, version, signed_at),
            )
            self._conn.commit()
        return {"anon_key": anon_key, "version": version, "signed_at": signed_at}

    def latest(self, anon_key: str) -> dict[str, Any] | None:
        """该匿名键最近一次签署记录；从未签署返回 None。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT anon_key, version, signed_at FROM agreements WHERE anon_key = ?"
                " ORDER BY id DESC LIMIT 1",
                (anon_key,),
            ).fetchone()
        if row is None:
            return None
        return {"anon_key": row["anon_key"], "version": row["version"], "signed_at": row["signed_at"]}

    def has_signed(self, anon_key: str, version: str = AGREEMENT_VERSION) -> bool:
        """是否已签署指定版本（缺省当版）——注册链路自检 / 合规核查用。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT EXISTS(SELECT 1 FROM agreements WHERE anon_key = ? AND version = ?)",
                (anon_key, version),
            ).fetchone()
        return bool(row[0])
