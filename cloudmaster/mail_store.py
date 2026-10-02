"""邮件报告与来信台账（ADR-009）——薄壳：实现已迁 storage/（v2.0.0 P1 统一 SQLite 底座）。

双 DAL 来源：InboxStore（来信台账，cloudmaster/storage/inbox.py，inbox_mails 表）
与 ReportRegistry（报告草稿/发送记录，cloudmaster/storage/reports.py，
report_drafts / report_sents 两表）。v2.0.0 P6 将本模块降级为同名再导出，既有
`from cloudmaster.mail_store import ...` 与测试不破；P3 删旧模块时统一改 import。

MailStoreError 单一类身份：reports 侧自 storage.inbox 导入同一类（P6 收口——
过渡期两 DAL 各持同名异类会让 `pytest.raises(MailStoreError)` 接不住 reports 侧
抛出），此处再导出的就是两侧共同抛出的那一个。

P1 已落库（business.db）：进程重启不丢（旧版 ReportRegistry 为纯内存 dict）；
发送记录仍只存交付元数据，**不落正文**。
"""

from .storage.inbox import InboxStore, MailStoreError
from .storage.reports import ReportRegistry

__all__ = ["InboxStore", "MailStoreError", "ReportRegistry"]
