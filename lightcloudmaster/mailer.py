"""邮件发送（ADR-009）——薄壳：实现已迁 services/mail/smtp.py。

v2.0.0 P6：MailError / OutgoingMail / SmtpChannel / RecordingChannel / Mailer
自本模块逐字迁入 lightcloudmaster/services/mail/smtp.py（唯一行为修改：确认令牌比对
改 secrets.compare_digest 常数时间比较，修计时侧信道）。此处同名再导出，既有
`from lightcloudmaster.mailer import ...` 与测试不破；P3 删旧模块时统一改 import 路径。

红线不变：未确认不发送/不产生发送记录；凭据只经环境变量；发送台账不落正文。
"""

from .services.mail.smtp import Mailer, MailError, OutgoingMail, RecordingChannel, SmtpChannel

__all__ = ["MailError", "Mailer", "OutgoingMail", "RecordingChannel", "SmtpChannel"]
