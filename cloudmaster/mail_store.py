"""邮件报告与来信台账（ADR-009）——薄壳：实现已迁 storage/（v2.0.0 P1 统一 SQLite 底座）。

双 DAL 来源：InboxStore（来信台账，cloudmaster/storage/inbox.py，inbox_mails 表）
与 ReportRegistry（报告草稿/发送记录，cloudmaster/storage/reports.py，
report_drafts / report_sents 两表）。v2.0.0 P6 将本模块降级为同名再导出，既有
`from cloudmaster.mail_store import ...` 与测试不破；P3 删旧模块时统一改 import。

注意：两个 DAL 各自持有同名的 MailStoreError（不同类，P3 删旧前过渡期允许重复）。
此处只再导出 storage/inbox 的那个——来信侧缺 uid/重复 uid 的参数错误最先经它
抛出；reports 侧缺 report_id 的报错在其自身模块内自洽。

P1 已落库（business.db）：进程重启不丢（旧版 ReportRegistry 为纯内存 dict）；
发送记录仍只存交付元数据，**不落正文**。
"""

from .storage.inbox import InboxStore, MailStoreError
from .storage.reports import ReportRegistry

__all__ = ["InboxStore", "MailStoreError", "ReportRegistry"]
