"""隐私保留期 DAL：统一业务库 privacy_settings 表，审计事件 append-only。

惰性默认不落盘：未设置键只返回 DEFAULT_RETENTION_DAYS。created_at 首次落库后
跨次更新保持不变（保留期可改、删除起算点不可改）。
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
    """保留期偏好（含创建时间）。"""

    def __init__(self, path: str | None = None):
        self._path: Path = db.resolve_db_path(path, "PRIVACY_DB_PATH")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn, self._lock = db.connect(self._path)

    def set_retention(self, key: str, days: int, *, now: datetime | None = None) -> dict[str, Any]:
        if days not in RETENTION_CHOICES:
            raise PrivacyError(f"保留期只支持 {list(RETENTION_CHOICES)} 天")
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
        # 数据主体权利行权痕迹：落审计并记录 created_at，证明删除起算点未被推移。
        db.record_audit(
            self._conn,
            self._lock,
            "retention_changed",
            key,
            {"days": days, "created_at": record["created_at"]},
        )
        return record

    def get_retention(self, key: str) -> dict[str, Any]:
        """未设置时返回默认 30 天，不落盘。"""
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
        """到期删除计划：created_at + retention_days。"""
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
        """已落库保留期偏好的匿名键（保留期真删除 jobs/purge 的扫描入口）。"""
        with self._lock:
            rows = self._conn.execute("SELECT anon_key FROM privacy_settings ORDER BY rowid").fetchall()
        return [row["anon_key"] for row in rows]

    def log_export(self, profile_key: str) -> None:
        db.record_audit(self._conn, self._lock, "data_exported", profile_key)

    def log_purge(self, purged_keys: list[str]) -> None:
        db.record_audit(
            self._conn,
            self._lock,
            "purge_executed",
            "",
            {"purged": purged_keys, "count": len(purged_keys)},
        )


def export_bundle(
    *,
    profile_key: str,
    profile: dict[str, Any] | None,
    messages: list[Any] | None,
    retention: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """一键导出：最小画像 + 会话消息 + 保留期。原文只回传本人，服务端不额外落盘。"""
    moment = now or datetime.now(UTC)
    items: list[dict[str, str]] = []
    for m in messages or []:
        role = "user" if getattr(m, "type", "") == "human" else "ai"
        items.append({"role": role, "text": str(getattr(m, "content", ""))})
    return {
        "exported_at": moment.isoformat(),
        "profile_key": profile_key,
        "profile": dict(profile or {}),
        "retention": retention or {},
        "message_count": len(items),
        "messages": items,
        "note": "导出内容仅含你的匿名最小画像与会话记录，不含姓名/联系方式。",
    }
