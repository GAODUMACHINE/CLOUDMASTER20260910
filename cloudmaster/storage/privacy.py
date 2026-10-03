"""隐私保留期 DAL（v2.0.0 P1 存储层）：旧 cloudmaster/privacy.py PrivacyStore 的 SQLite 移植。

设计取舍（重写计划 §15b.3/§16）：
- 公开 API 与旧 JSON 版逐字一致（类名/方法签名/异常与中文文案/返回 dict 的键值语义），
  「调用方零改动切换」是本层存在的意义；export_bundle 是与存储无关的纯函数，留在原模块不随迁。
- 常量与 PrivacyError 原样复制进本模块保持自包含（旧模块 P3 才删，暂时允许重复）。
- 落位统一业务库 privacy_settings 表（DDL 见 db.py，retention_days 另有数据库级 CHECK 兜底）；
  Python 侧校验先行，保证 PrivacyError 文案与旧版逐字一致。
- 惰性默认不落盘：未设置键只返回 DEFAULT_RETENTION_DAYS，不写入任何行（隐私最小化）。
- created_at 首次落库后跨次更新保持不变（保留期可改、删除起算点不可改），
  故 INSERT OR REPLACE 前先 SELECT 旧 created_at。
- 审计自 v2.0.0 P4 起在本层统一记录（db.record_audit，audit_events append-only 触发器
  兜底禁改禁删）：retention_changed（改保留期）/ data_exported（导出）/ purge_executed
  （批量清除）。审计事件只落匿名键与动作参数，绝不落对话内容。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import db

RETENTION_CHOICES = (7, 30, 90)
DEFAULT_RETENTION_DAYS = 30


class PrivacyError(ValueError):
    pass


class PrivacyStore:
    """保留期偏好（含创建时间），统一业务库 privacy_settings 表。"""

    def __init__(self, path: str | None = None):
        # 路径收口：显式参数 → PRIVACY_DB_PATH → BUSINESS_DB_PATH → 统一库缺省；
        # 与旧版一致地确保父目录存在（缺省 data/private/ 首次运行时可能缺失）。
        self._path: Path = db.resolve_db_path(path, "PRIVACY_DB_PATH")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn, self._lock = db.connect(self._path)

    def set_retention(self, key: str, days: int, *, now: datetime | None = None) -> dict[str, Any]:
        if days not in RETENTION_CHOICES:
            raise PrivacyError(f"保留期只支持 {list(RETENTION_CHOICES)} 天")
        # now 可注入（旧签名如此，测试依赖）；未注入时统一走 db.now_iso()。
        stamp = now.isoformat() if now is not None else db.now_iso()
        with self._lock:
            row = self._conn.execute(
                "SELECT created_at FROM privacy_settings WHERE anon_key = ?", (key,)
            ).fetchone()
            record = {
                "retention_days": days,
                "created_at": (row["created_at"] if row else None) or stamp,
                "updated_at": stamp,
            }
            self._conn.execute(
                "INSERT OR REPLACE INTO privacy_settings"
                " (anon_key, retention_days, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (key, days, record["created_at"], record["updated_at"]),
            )
            self._conn.commit()
        # 保留期是《办法》第 17/19 条项下的数据主体权利行权痕迹：落 append-only 审计
        # （created_at 一并记录，证明删除起算点未被本次变更推移）。
        db.record_audit(
            self._conn,
            self._lock,
            "retention_changed",
            key,
            {"days": days, "created_at": record["created_at"]},
        )
        return record

    def get_retention(self, key: str) -> dict[str, Any]:
        """未设置时返回默认 30 天，不落盘（惰性默认）。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT retention_days, created_at, updated_at FROM privacy_settings WHERE anon_key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return {"retention_days": DEFAULT_RETENTION_DAYS, "created_at": None, "updated_at": None}
        return {
            "retention_days": row["retention_days"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def purge_schedule(self, key: str, *, now: datetime | None = None) -> dict[str, Any]:
        """到期删除计划：created_at + retention_days（纯 Python 计算，逐字沿用旧实现）。"""
        moment = now or datetime.now(UTC)
        record = self.get_retention(key)
        created_raw = record.get("created_at")
        days = record["retention_days"]
        if not created_raw:
            return {
                "retention_days": days,
                "delete_after": None,
                "expired": False,
                "note": "尚无会话创建时间记录，删除计划自首次会话起算。",
            }
        try:
            created = datetime.fromisoformat(created_raw)
        except ValueError:
            created = moment
        delete_after = created + timedelta(days=days)
        return {
            "retention_days": days,
            "delete_after": delete_after.isoformat(),
            "expired": moment >= delete_after,
            "note": "到期后会话数据将被删除。",
        }

    def forget(self, key: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM privacy_settings WHERE anon_key = ?", (key,))
            self._conn.commit()
            return cur.rowcount > 0

    def all_keys(self) -> list[str]:
        """全部已落库保留期偏好的匿名键（按 rowid 稳定序）。

        保留期真删除（jobs/purge）的扫描入口：惰性默认键未落库、无会话数据可删，
        故只需扫描已落库键；不存在的键 purge_schedule 走「尚无创建时间」分支自然跳过。
        """
        with self._lock:
            rows = self._conn.execute("SELECT anon_key FROM privacy_settings ORDER BY rowid").fetchall()
        return [row["anon_key"] for row in rows]

    def log_export(self, profile_key: str) -> None:
        """导出行为审计（数据主体知情权：用户可查知自己的数据曾被导出过几次）。"""
        db.record_audit(self._conn, self._lock, "data_exported", profile_key)

    def log_purge(self, purged_keys: list[str]) -> None:
        """批量清除审计（jobs/purge 每轮执行后调用；anon_key 留空、键清单入 detail）。"""
        db.record_audit(
            self._conn,
            self._lock,
            "purge_executed",
            "",
            {"purged": purged_keys, "count": len(purged_keys)},
        )
