"""IMAP 收件通道（ADR-009）：连接与拉取 UNSEEN，解析委托同包 parse。

v2.0.0 P6：ImapInbox 自 cloudmaster/inbox.py 逐字迁入 services/mail（纯函数解析
已拆至同包 parse.py；旧根模块降级为薄壳同名再导出）。

红线：凭据经构造参数注入（生产由环境变量读出后传入），本模块不做任何持久化，
也不在异常消息外记录凭据；默认只拉取 UNSEEN，避免重复处理；网络/认证失败抛
InboxError（不静默返回空）。
"""

from __future__ import annotations

import imaplib

from .parse import InboxError, ReceivedMail, parse_message


class ImapInbox:
    """IMAP 收件通道（标准库 imaplib）。默认只拉取 UNSEEN，避免重复处理。"""

    def __init__(
        self,
        *,
        host: str,
        port: int = 993,
        user: str = "",
        password: str = "",
        folder: str = "INBOX",
        timeout: float = 20.0,
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.folder = folder
        self.timeout = timeout

    def fetch_unseen(self, *, limit: int = 20, mark_seen: bool = True) -> list[ReceivedMail]:
        """拉取未读邮件并解析。网络/认证失败抛 InboxError（不静默返回空）。"""
        try:
            conn = imaplib.IMAP4_SSL(self.host, self.port, timeout=self.timeout)
        except (OSError, imaplib.IMAP4.error) as exc:
            raise InboxError(f"IMAP 连接失败：{exc}") from exc
        try:
            conn.login(self.user, self.password)
            conn.select(self.folder)
            typ, data = conn.search(None, "UNSEEN")
            if typ != "OK":
                raise InboxError("IMAP 搜索未读失败")
            uids = (data[0] or b"").split()
            out: list[ReceivedMail] = []
            for num in uids[-limit:]:
                uid = num.decode("ascii", errors="replace")
                typ2, payload = conn.fetch(num, "(RFC822)")
                if typ2 != "OK" or not payload or not isinstance(payload[0], tuple):
                    continue
                raw = payload[0][1]
                out.append(parse_message(raw, uid=uid))
                if mark_seen:
                    conn.store(num, "+FLAGS", "\\Seen")
            return out
        except imaplib.IMAP4.error as exc:
            raise InboxError(f"IMAP 操作失败：{exc}") from exc
        finally:
            try:
                conn.logout()
            except (OSError, imaplib.IMAP4.error):
                pass
