"""用户画像 DAL（v2.0.0 存储层，ADR-002 最小画像）：profiles 表。

对旧 cloudmaster/profile_store.py（JSON 文件版）的 1:1 SQLite 移植：类名 / 方法签名 /
ProfileValidationError 与中文文案（逐字）/ 返回值语义完全一致，调用方零改动切换。
白名单 7 字段（age / is_minor / guardian_contact_available / emergency_contact_available /
dependency_tendency / email / report_opt_in）与注释自旧模块原样复制，保持自包含
（旧模块 P3 才删，过渡期允许重复）。

设计取舍（混合「类型列 + data_json」）：
- data_json 存 json.dumps(校验后 dict)——**读侧权威**：get() 返回 json.loads 的精确副本，
  显式 None 与缺省键的区别、字段顺序之外的任何形态细节均逐字节往返，报告/导出等
  消费方零适配。
- 类型列冗余存同值（缺省字段为 NULL）：只为 email 回查（find_keys_by_email）能在
  列上做 TRIM/LOWER 等值匹配并走 idx_profiles_email，不必全表反序列化；其余列
  供 P4 数据治理（如未成年台账）直查，读侧一律以 data_json 为准。
- put() 整体替换语义 = 旧 `self._data[key] = cleaned`：UPSERT 的 DO UPDATE 覆盖
  全部列（含置 NULL），created_at 首次写入后保持不变，updated_at 每次 put 刷新。
- 邮箱比较忽略大小写与首尾空白（与旧一致）；注册邮箱经 _EMAIL_RE 校验为 ASCII，
  SQLite LOWER() 的 ASCII 语义足够。返回顺序按 rowid（= 首次注册序，对应旧 dict
  插入序）。
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
    # ADR-009：注册邮箱（计划书 3.1.3-8）。属最小必要采集的**唯一例外**，
    # 因「疏导报告经确认后发至注册邮箱」必须要有投递地址；可查看、可删除、可退订。
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
        # 与旧实现一致：父目录不存在则先建（生产缺省 data/private/）。
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

        **逐列显式排列，严格对齐 put() INSERT 的列清单**：
        (age, is_minor, guardian, emergency, dependency, email, report_opt_in)。
        勿改回「布尔列循环展开 + email 收尾」的写法——_BOOL_COLUMNS 以 report_opt_in
        结尾、列清单以 email 在前，循环展开会把两列绑反（v2.0.0 回归实测踩过：
        email 列存进 '1'，find_keys_by_email 永远查不到，STOP 退订静默失效）。
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
        """删除画像（幂等，不泄露标识是否存在）。成功删除时落 data_deleted 审计。

        reason 取值：user_delete（用户主动退出，《办法》第 19 条）/ retention_purge
        （保留期到点清除，jobs/purge）——审计里区分「用户行权」与「系统履约」两种删除。
        """
        with self._lock:
            cur = self._conn.execute("DELETE FROM profiles WHERE anon_key = ?", (key,))
            self._conn.commit()
        deleted = cur.rowcount > 0
        if deleted:
            # 只在确有行被删时落审计：幂等重删（含不存在的键）不产生噪声事件，
            # 也不泄露「该匿名标识是否存在」。
            db.record_audit(self._conn, self._lock, "data_deleted", key, {"reason": reason})
        return deleted

    def clear_all(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM profiles")
            self._conn.commit()

    def find_keys_by_email(self, email: str) -> list[str]:
        """按注册邮箱回查匿名标识（ADR-009 退信用：IMAP 收到 STOP 后据此退订）。

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
