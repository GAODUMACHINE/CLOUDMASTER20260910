"""集成：邮件收发闭环（ADR-009）——报告二次确认发送 / 退订 / 收信解析入库 / STOP 自动退订。

全 fake：注入 RecordingChannel 与假 IMAP 收件箱，禁触网、禁真实邮件。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from cloudmaster.graph import build_graph
from cloudmaster.inbox import KIND_BOUNCE, KIND_REPLY, ReceivedMail
from cloudmaster.mail_store import InboxStore, ReportRegistry
from cloudmaster.mailer import Mailer, RecordingChannel
from cloudmaster.privacy import PrivacyStore
from cloudmaster.profile_store import ProfileStore
from cloudmaster.review_queue import ReviewLedger
from cloudmaster.web_app import create_app

MAIL = "user@example.com"
TOKEN = "review-token"


class FakeInbox:
    """假 IMAP 收件箱：返回预置来信，并记录是否被标记已读。"""

    def __init__(self, mails):
        self._mails = list(mails)
        self.calls = 0
        self.fail_with = None

    def fetch_unseen(self, *, limit: int = 20, mark_seen: bool = True):
        self.calls += 1
        if self.fail_with is not None:
            raise self.fail_with
        return self._mails[:limit]


def _client(tmp_path, llm, *, channel=None, inbox=None):
    store = ProfileStore(str(tmp_path / "w.json"))
    mailer = Mailer(channel, from_addr="sys@example.com", from_name="云上高士")
    app = create_app(
        graph=build_graph(llm, checkpointer=None),
        store=store,
        mailer=mailer,
        expected_token="tok",
        reviews=ReviewLedger(str(tmp_path / "reviews.jsonl")),
        privacy=PrivacyStore(str(tmp_path / "privacy.json")),
        inbox_store=InboxStore(str(tmp_path / "inbox.jsonl")),
        reports=ReportRegistry(),
        inbox=inbox,
        reviewer_token=TOKEN,
        report_salt="test-salt",
    )
    return TestClient(app), store, channel


def _register(c, age=22, email=MAIL):
    return c.post("/api/register", json={"age": age, "email": email}).json()["profile_key"]


# ---- 报告草稿 → 二次确认 → 发送 ----


def test_report_draft_requires_registration(tmp_path, fake_llm_empathic):
    c, _, _ = _client(tmp_path, fake_llm_empathic)
    assert c.get("/api/report/anon-missing").status_code == 404


def test_report_draft_contains_no_raw_conversation(tmp_path, fake_llm_empathic):
    c, _, _ = _client(tmp_path, fake_llm_empathic)
    key = _register(c)
    c.post("/api/chat", json={"profile_key": key, "text": "这是一句不该出现在报告里的原话"})
    draft = c.get(f"/api/report/{key}").json()
    assert draft["report_id"].startswith("RP-")
    assert draft["contains_raw_conversation"] is False
    assert "这是一句不该出现在报告里的原话" not in draft["body"]
    assert draft["confirm_token"] and draft["recipient"] == MAIL
    assert draft["disclaimer"]


def test_report_send_requires_confirm_token(tmp_path, fake_llm_empathic):
    c, _, ch = _client(tmp_path, fake_llm_empathic, channel=RecordingChannel())
    key = _register(c)
    draft = c.get(f"/api/report/{key}").json()
    bad = c.post(
        "/api/report/send",
        json={"report_id": draft["report_id"], "confirm_token": "wrong"},
    )
    assert bad.status_code == 403
    assert ch.messages == []


def test_report_send_rejected_when_user_declines(tmp_path, fake_llm_empathic):
    """产品级 HITL：用户不确认就不发送。"""
    c, _, ch = _client(tmp_path, fake_llm_empathic, channel=RecordingChannel())
    key = _register(c)
    draft = c.get(f"/api/report/{key}").json()
    out = c.post(
        "/api/report/send",
        json={
            "report_id": draft["report_id"],
            "confirm_token": draft["confirm_token"],
            "decision": "reject",
        },
    ).json()
    assert out["sent"] is False
    assert ch.messages == []


def test_report_send_success_and_no_double_send(tmp_path, fake_llm_empathic):
    c, _, ch = _client(tmp_path, fake_llm_empathic, channel=RecordingChannel())
    key = _register(c)
    draft = c.get(f"/api/report/{key}").json()
    out = c.post(
        "/api/report/send",
        json={"report_id": draft["report_id"], "confirm_token": draft["confirm_token"]},
    ).json()
    assert out["sent"] is True and out["delivery"]["to"] == MAIL
    assert len(ch.messages) == 1
    assert draft["report_id"] in ch.messages[0].subject
    # 重复提交同一报告必须被拒（避免重复投递）
    again = c.post(
        "/api/report/send",
        json={"report_id": draft["report_id"], "confirm_token": draft["confirm_token"]},
    )
    assert again.status_code == 409
    assert len(ch.messages) == 1


def test_report_send_without_channel_fails_loudly(tmp_path, fake_llm_empathic):
    """红线：未配置 SMTP 通道时不得假装发送成功。"""
    c, _, _ = _client(tmp_path, fake_llm_empathic, channel=None)
    key = _register(c)
    draft = c.get(f"/api/report/{key}").json()
    out = c.post(
        "/api/report/send",
        json={"report_id": draft["report_id"], "confirm_token": draft["confirm_token"]},
    ).json()
    assert out["sent"] is False and "未配置" in out["reason"]
    assert draft["mail_channel_ready"] is False


def test_report_send_blocked_after_unsubscribe(tmp_path, fake_llm_empathic):
    c, _, ch = _client(tmp_path, fake_llm_empathic, channel=RecordingChannel())
    key = _register(c)
    assert c.post(f"/api/report/unsubscribe/{key}").json()["opt_in"] is False
    draft = c.get(f"/api/report/{key}").json()
    assert draft["opt_in"] is False
    out = c.post(
        "/api/report/send",
        json={"report_id": draft["report_id"], "confirm_token": draft["confirm_token"]},
    ).json()
    assert out["sent"] is False
    assert ch.messages == []
    # 可重新开启
    assert c.post(f"/api/report/resubscribe/{key}").json()["opt_in"] is True


def test_report_status_reports_recipient_and_channel(tmp_path, fake_llm_empathic):
    c, _, _ = _client(tmp_path, fake_llm_empathic, channel=RecordingChannel())
    key = _register(c)
    st = c.get(f"/api/report/status/{key}").json()
    assert st["recipient"] == MAIL and st["mail_channel_ready"] is True and st["sent_count"] == 0


# ---- IMAP 收信 ----


def test_inbox_poll_requires_reviewer_token(tmp_path, fake_llm_empathic):
    c, _, _ = _client(tmp_path, fake_llm_empathic, inbox=FakeInbox([]))
    assert c.post("/api/inbox/poll").status_code == 403
    assert c.get("/api/inbox").status_code == 403


def test_inbox_poll_without_channel_is_503(tmp_path, fake_llm_empathic):
    c, _, _ = _client(tmp_path, fake_llm_empathic, inbox=None)
    assert c.post("/api/inbox/poll", params={"token": TOKEN}).status_code == 503


def test_inbox_poll_stores_replies_and_dedups(tmp_path, fake_llm_empathic):
    mails = [
        ReceivedMail(
            uid="1",
            kind=KIND_REPLY,
            from_addr=MAIL,
            subject="Re: [RP-1] x",
            date="",
            ticket="RP-1",
            body="谢谢",
        ),
        ReceivedMail(uid="2", kind=KIND_BOUNCE, from_addr="", subject="bounce", date="", ticket="", body=""),
    ]
    fake = FakeInbox(mails)
    c, _, _ = _client(tmp_path, fake_llm_empathic, inbox=fake)
    out = c.post("/api/inbox/poll", params={"token": TOKEN}).json()
    assert out["fetched"] == 2 and out["stored"] == 2
    listed = c.get("/api/inbox", params={"token": TOKEN}).json()
    assert listed["count"] == 2
    # 同一批再次拉取：uid 去重，不再重复入库
    out2 = c.post("/api/inbox/poll", params={"token": TOKEN}).json()
    assert out2["stored"] == 0
    assert c.get("/api/inbox", params={"token": TOKEN}).json()["count"] == 2


def test_inbox_stop_unsubscribes_matching_profile(tmp_path, fake_llm_empathic):
    """邮件的「STOP 退订」必须真正生效（按发件地址回查匿名标识）。"""
    c, store, _ = _client(tmp_path, fake_llm_empathic, inbox=FakeInbox([]))
    key = _register(c)
    assert store.get(key)["report_opt_in"] is True
    fake = FakeInbox(
        [
            ReceivedMail(
                uid="9",
                kind=KIND_REPLY,
                from_addr=MAIL,
                subject="STOP",
                date="",
                ticket="",
                body="请不要再发",
                stop_requested=True,
            )
        ]
    )
    c.app  # noqa: B018 -- 保持引用清晰
    c2, _, _ = _client(tmp_path, fake_llm_empathic, inbox=fake)
    # 用同一 store 重新构造客户端以保证命中同一画像
    app = create_app(
        graph=build_graph(fake_llm_empathic, checkpointer=None),
        store=store,
        mailer=Mailer(RecordingChannel()),
        reviews=ReviewLedger(str(tmp_path / "r2.jsonl")),
        privacy=PrivacyStore(str(tmp_path / "p2.json")),
        inbox_store=InboxStore(str(tmp_path / "i2.jsonl")),
        reports=ReportRegistry(),
        inbox=fake,
        reviewer_token=TOKEN,
    )
    c3 = TestClient(app)
    out = c3.post("/api/inbox/poll", params={"token": TOKEN}).json()
    assert out["unsubscribed"] == [key]
    assert store.get(key)["report_opt_in"] is False


def test_inbox_poll_propagates_imap_failure(tmp_path, fake_llm_empathic):
    from cloudmaster.inbox import InboxError

    fake = FakeInbox([])
    fake.fail_with = InboxError("IMAP 连接失败：boom")
    c, _, _ = _client(tmp_path, fake_llm_empathic, inbox=fake)
    r = c.post("/api/inbox/poll", params={"token": TOKEN})
    assert r.status_code == 502 and "IMAP" in r.json()["detail"]


def test_review_detail_shows_linked_replies(tmp_path, fake_llm_crisis_danger):
    """人工审核台应能看到针对该工单的邮件回信。"""
    fake = FakeInbox(
        [
            ReceivedMail(
                uid="5",
                kind=KIND_REPLY,
                from_addr=MAIL,
                subject="Re: [HR-x] 我来补充情况",
                date="",
                ticket="",
                body="补充",
            )
        ]
    )
    c, _, _ = _client(tmp_path, fake_llm_crisis_danger, inbox=fake)
    key = _register(c)
    ticket = c.post("/api/chat", json={"profile_key": key, "text": "我不想活了"}).json()["escalation"][
        "ticket_id"
    ]
    detail = c.get(f"/api/review/{ticket}", params={"token": TOKEN}).json()
    assert "replies" in detail and isinstance(detail["replies"], list)
