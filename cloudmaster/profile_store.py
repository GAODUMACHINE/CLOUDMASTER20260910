"""Profile Store（v0.2.0 最小画像，ADR-002）。文件后备 JSON，字段白名单（隐私最小化），
get/put/delete——可查看、可清除。服务层注入 user_profile，图内只读。"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

ALLOWED_FIELDS = {
    "age": int,
    "is_minor": bool,
    "guardian_contact_available": bool,
    "emergency_contact_available": bool,
    "dependency_tendency": bool,
}


class ProfileValidationError(ValueError):
    pass


class ProfileStore:
    def __init__(self, path: str | None = None):
        raw = path or os.environ.get("PROFILE_DB_PATH", "")
        self._path = Path(raw) if raw else Path("data/private/profile.json")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        try:
            self._data = json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            self._data = {}

    def _save(self) -> None:
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._path)

    def _validate(self, profile: dict[str, Any]) -> dict[str, Any]:
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

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._data[key]) if key in self._data else None

    def has(self, key: str) -> bool:
        with self._lock:
            return key in self._data

    def put(self, key: str, profile: dict[str, Any]) -> None:
        cleaned = self._validate(profile)
        with self._lock:
            self._data[key] = cleaned
            self._save()

    def delete(self, key: str) -> bool:
        with self._lock:
            existed = key in self._data
            if existed:
                del self._data[key]
                self._save()
            return existed

    def clear_all(self) -> None:
        with self._lock:
            self._data = {}
            self._save()
