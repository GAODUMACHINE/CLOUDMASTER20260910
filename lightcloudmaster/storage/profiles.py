"""用户画像 DAL：profiles 表（最小画像白名单 7 字段）。

data_json 存校验后的完整 dict（读侧权威，get() 返回精确副本）；类型列冗余存同值，
只为 email 回查（find_keys_by_email）能走 idx_profiles_email 列上匹配，其余列供
数据治理直查。put() 整体替换语义：UPSERT 覆盖全部列，created_at 首次写入后不变。
邮箱比较忽略大小写与首尾空白；返回顺序按 rowid（首次注册序）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import db

ALLOWED_FIELDS = {
    "age": int,
    "is_minor": bool,
    "guardian_contact_available": bool,
    "emergency_contact_available": bool,
    "dependency_tendency": bool,
    # 注册邮箱：最小必要采集的唯一例外——「疏导报告经确认后发至注册邮箱」必须有
    # 投递地址；可查看、可删除、可退订。
    "email": str,
    # 报告订阅开关（默认可发；用户回信 STOP 或前端退订即置 False）
    "report_opt_in": bool,
}


class ProfileValidationError(ValueError):
    pass


# 布尔列的写侧映射（None 保持 NULL；True/False → 1/0）。
_BOOL_COLUMNS = (
    "is_minor",
    "guardian_contact_available",
    "emergency_contact_available",
    "dependency_tendency",
    "report_opt_in",
)


class ProfileStore:
    """用户画像存储（SQLite business.db，经 storage.db 共享连接与锁）。"""

    def __init__(self, path: str | None = None):
        self._path = db.resolve_db_path(path, "PROFILE_DB_PATH")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn, self._lock = db.connect(self._path)

    @property
    def path(self) -> Path:
        return self._path

    @staticmethod
    def _validate(profile: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(profile, dict):
            raise ProfileValidationError("profile 必须是 dict")
        unknown = set(profile) - set(ALLOWED_FIELDS)
        if unknown:
            raise ProfileValidationError(f"不允许的画像字段: {sorted(unknown)}")
        for k, v in profile.items():
            expected = ALLOWED_FIELDS[k]
            if v is not None and not isinstance(v, expected):
                raise ProfileValidationError(f"字段 {k} 类型应为 {expected.__name__}")
        return dict(profile)

    @staticmethod
    def _typed_values(cleaned: dict[str, Any]) -> tuple[Any, ...]:
        """校验后 dict → 类型列值（缺省字段为 None）。

        逐列显式排列，严格对齐 put() INSERT 的列清单：email 在前、report_opt_in
        在后——循环展开会把两列绑反（email 列存进 '1'，退订回查静默失效）。
        """

        def col(name: str) -> Any:
            v = cleaned.get(name)
            if v is None:
                return None
            return int(v) if name in _BOOL_COLUMNS else v

        return (
            col("age"),
            col("is_minor"),
            col("guardian_contact_available"),
            col("emergency_contact_available"),
            col("dependency_tendency"),
            col("email"),
            col("report_opt_in"),
        )

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT data_json FROM profiles WHERE anon_key = ?", (key,)).fetchone()
        return json.loads(row["data_json"]) if row is not None else None

    def has(self, key: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT EXISTS(SELECT 1 FROM profiles WHERE anon_key = ?)", (key,)
            ).fetchone()
        return bool(row[0])

    def put(self, key: str, profile: dict[str, Any]) -> None:
        cleaned = self._validate(profile)
        data_json = json.dumps(cleaned, ensure_ascii=False)
        now = db.now_iso()
        with self._lock:
            self._conn.execute(
                "INSERT INTO profiles"
                " (anon_key, age, is_minor, guardian_contact_available,"
                " emergency_contact_available, dependency_tendency, email, report_opt_in,"
                " data_json, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(anon_key) DO UPDATE SET"
                " age=excluded.age, is_minor=excluded.is_minor,"
                " guardian_contact_available=excluded.guardian_contact_available,"
                " emergency_contact_available=excluded.emergency_contact_available,"
                " dependency_tendency=excluded.dependency_tendency, email=excluded.email,"
                " report_opt_in=excluded.report_opt_in, data_json=excluded.data_json,"
                " updated_at=excluded.updated_at",
                (key, *self._typed_values(cleaned), data_json, now, now),
            )
            self._conn.commit()

    def delete(self, key: str, *, reason: str = "user_delete") -> bool:
        """删除画像（幂等）。成功删除时落 data_deleted 审计。

        reason 取值：user_delete（用户主动退出）/ retention_purge（保留期到点清除，
        jobs/purge）——审计里区分「用户行权」与「系统履约」。
        """
        with self._lock:
            cur = self._conn.execute("DELETE FROM profiles WHERE anon_key = ?", (key,))
            self._conn.commit()
        deleted = cur.rowcount > 0
        if deleted:
            # 只在确有行被删时落审计：幂等重删不产生噪声事件，也不泄露键是否存在。
            db.record_audit(self._conn, self._lock, "data_deleted", key, {"reason": reason})
        return deleted

    def clear_all(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM profiles")
            self._conn.commit()

    def find_keys_by_email(self, email: str) -> list[str]:
        """按注册邮箱回查匿名标识（收信侧 STOP 退订用）。

        只做列上等值匹配，不写日志、不外泄；邮箱比较忽略大小写与首尾空白。
        """
        target = (email or "").strip().lower()
        if not target:
            return []
        with self._lock:
            rows = self._conn.execute(
                "SELECT anon_key FROM profiles WHERE TRIM(LOWER(email)) = TRIM(LOWER(?)) ORDER BY rowid",
                (target,),
            ).fetchall()
        return [row["anon_key"] for row in rows]
