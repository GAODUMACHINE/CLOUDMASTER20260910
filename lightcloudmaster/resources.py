"""资源台账薄壳（v2.0.0 P3，ADR-011 §1）：ResourceStore 实现已迁 storage/resources.py
（统一 SQLite 底座，ADR-012），本模块保留同名再导出——既有
`from lightcloudmaster.resources import ResourceStore, ResourceError` 不破。
红线不变（TC-RES-001~003）：不硬编码任何真实热线号码，未审核号码一律不下发。
"""

from .storage.resources import RESOURCE_KINDS, ResourceError, ResourceStore

__all__ = ["RESOURCE_KINDS", "ResourceError", "ResourceStore"]
