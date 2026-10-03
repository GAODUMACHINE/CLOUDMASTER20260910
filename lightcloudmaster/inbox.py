"""邮件接收（ADR-009）——薄壳：实现已迁 services/mail。

v2.0.0 P6：纯函数解析（KIND_* 常量 / InboxError / ReceivedMail / parse_message）
迁 lightcloudmaster/services/mail/parse.py，ImapInbox 迁 .../imap.py，收件编排
（poll_inbox，自 web 端点抽离）迁 .../ingest.py。此处同名再导出，既有
`from lightcloudmaster.inbox import ...` 与测试不破；P3 删旧模块时统一改 import 路径。

红线不变：不下载附件；正文截断（parse 侧负责）后才入库；凭据只经环境变量。
"""

from .services.mail.imap import ImapInbox
from .services.mail.parse import (
    KIND_AUTO,
    KIND_BOUNCE,
    KIND_OTHER,
    KIND_REPLY,
    InboxError,
    ReceivedMail,
    parse_message,
)

__all__ = [
    "ImapInbox",
    "InboxError",
    "KIND_AUTO",
    "KIND_BOUNCE",
    "KIND_OTHER",
    "KIND_REPLY",
    "ReceivedMail",
    "parse_message",
]
