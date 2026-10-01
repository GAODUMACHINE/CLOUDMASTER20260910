"""邮件接收（ADR-009）：IMAP 拉取 + 回信/退信/退订解析。

合规与隐私：
- 只读取邮件头与正文纯文本，**不下载附件**（避免把任意文件引入系统）；
- 正文按需截断（默认 2000 字）后才入库，且落 `data/private/`（gitignored）；
- 支持 STOP 退订：识别到退订意图即置 `report_opt_in=False`。

分层：`parse_message()` 为**纯函数**（给定 bytes → 结构化结果，可离线单测）；
`ImapInbox` 只负责连接与拉取，凭据经环境变量注入。
"""

from __future__ import annotations

import email
import imaplib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr
from typing import Any

# 回信归属：从主题中提取受理编号 / 报告编号（如 [HR-xxxx] / [RP-xxxx]）
_TICKET_RE = re.compile(r"\[((?:HR|RP|AP)-[A-Za-z0-9]+)\]")
# 退订意图（中英）
_STOP_RE = re.compile(r"(^\s*STOP\s*$|退订|停止发送|不要再发|取消订阅|unsubscribe)", re.IGNORECASE)
# 退信识别：主题/发件人特征
_BOUNCE_RE = re.compile(
    r"(mail delivery (failed|subsystem)|undelivered mail|delivery status notification|"
    r"returned mail|failure notice|退信|投递失败)",
    re.IGNORECASE,
)
# 疑似自动回复（避免把机器人当作用户回信）
_AUTO_RE = re.compile(
    r"(out of office|auto(matic)?[ -]?reply|自动回复|auto-submitted:\s*auto)", re.IGNORECASE
)

KIND_REPLY = "reply"
KIND_BOUNCE = "bounce"
KIND_AUTO = "auto"
KIND_OTHER = "other"


class InboxError(RuntimeError):
    pass


@dataclass
class ReceivedMail:
    """一封已解析的来信（结构化，便于入库与判定）。"""

    uid: str
    kind: str
    from_addr: str
    subject: str
    date: str
    ticket: str
    body: str
    stop_requested: bool = False
    raw_size: int = 0

    def to_record(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "kind": self.kind,
            "from_addr": self.from_addr,
            "subject": self.subject,
            "date": self.date,
            "ticket": self.ticket,
            "body": self.body,
            "stop_requested": self.stop_requested,
            "fetched_at": datetime.now(UTC).isoformat(),
        }


def _decode(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except (UnicodeDecodeError, LookupError, ValueError):
        return str(raw)


def _plain_body(msg: Message, limit: int) -> str:
    """只取 text/plain，跳过附件与 HTML（不把外部内容当正文渲染）。"""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if part.get_content_disposition() == "attachment":
                continue
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True) or b""
                return payload.decode(part.get_content_charset() or "utf-8", errors="replace")[:limit]
        return ""
    if msg.get_content_type() == "text/plain":
        payload = msg.get_payload(decode=True) or b""
        return payload.decode(msg.get_content_charset() or "utf-8", errors="replace")[:limit]
    return ""


def parse_message(raw: bytes, *, uid: str = "", body_limit: int = 2000) -> ReceivedMail:
    """纯函数：把原始邮件字节解析为结构化来信。"""
    msg = email.message_from_bytes(raw)
    subject = _decode(msg.get("Subject"))
    from_addr = parseaddr(_decode(msg.get("From")))[1]
    date = _decode(msg.get("Date"))
    body = _plain_body(msg, body_limit).strip()

    ticket_match = _TICKET_RE.search(subject)
    ticket = ticket_match.group(1) if ticket_match else ""

    haystack = subject + " " + from_addr
    if _BOUNCE_RE.search(haystack) or not from_addr:
        kind = KIND_BOUNCE
    elif _AUTO_RE.search(haystack) or _AUTO_RE.search(_decode(msg.get("Auto-Submitted"))):
        kind = KIND_AUTO
    elif ticket:
        kind = KIND_REPLY
    else:
        kind = KIND_OTHER

    stop = bool(_STOP_RE.search(subject) or _STOP_RE.search(body))
    return ReceivedMail(
        uid=uid,
        kind=kind,
        from_addr=from_addr,
        subject=subject[:300],
        date=date[:100],
        ticket=ticket,
        body=body,
        stop_requested=stop,
        raw_size=len(raw),
    )


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
