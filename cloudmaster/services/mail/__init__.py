"""邮件链路（ADR-009）：smtp 发信（HITL 闸门）/ imap+parse 收信 / ingest 编排。

v2.0.0 P6 自根模块（mailer.py / inbox.py）迁入：发信与收信实现集中于本包，
旧根模块降级为薄壳同名再导出（既有 import 与测试不破）；台账 DAL 已在 P1 落
storage/（inbox.InboxStore / reports.ReportRegistry），本包不碰盘。

红线：未确认不发送、不产生发送记录；凭据只经环境变量注入；发送台账不落正文；
来信正文截断（parse 侧负责）后才入库。
"""
