"""申诉台账薄壳（v2.0.0 P3，ADR-011 §1）：AppealStore 实现已迁 storage/appeals.py
（统一 SQLite 底座，ADR-012；v2.0.0 P4 起 appeal_events 处置闭环启用——
submit 同事务落 received 事件，add_event/events/list_open 为运维通道），
本模块保留同名再导出——既有 `from lightcloudmaster.appeals import AppealStore` 不破。
历史：《办法》第 21 条 / TC-PRIV-006。
"""

from .storage.appeals import (
    APPEAL_ACTIONS,
    APPEAL_KINDS,
    AppealError,
    AppealStore,
)

__all__ = ["APPEAL_ACTIONS", "APPEAL_KINDS", "AppealError", "AppealStore"]
