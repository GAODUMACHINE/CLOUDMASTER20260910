"""画像薄壳（v2.0.0 P3，ADR-011 §1）：ProfileStore 实现已迁 storage/profiles.py
（统一 SQLite 底座，ADR-012），本模块保留同名再导出——既有
`from lightcloudmaster.profile_store import ProfileStore, ProfileValidationError` 不破
（server.py 与全部测试的注入路径零改动）。历史：ADR-002 最小画像起。
"""

from .storage.profiles import ALLOWED_FIELDS, ProfileStore, ProfileValidationError

__all__ = ["ALLOWED_FIELDS", "ProfileStore", "ProfileValidationError"]
