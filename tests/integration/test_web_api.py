"""集成（v0.5.0 web）：注册年龄门 + chat + SSE 流式 + 邮件 HITL（全 fake，禁触网）。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from cloudmaster.graph import build_graph
from cloudmaster.mailer import Mailer
from cloudmaster.profile_store import ProfileStore
from cloudmaster.web_app import create_app


def _client(tmp_path, fake_llm_empathic, expected_token="tok"):
    store = ProfileStore(str(tmp_path / "w.json"))
    mailer = Mailer()
    app = create_app(
        graph=build_graph(fake_llm_empathic, checkpointer=None),
        store=store,
        mailer=mailer,
        expected_token=expected_token,
    )
    return TestClient(app), store, mailer


def test_register_adult_ok(tmp_path, fake_llm_empathic):
    c, store, _ = _client(tmp_path, fake_llm_empathic)
    r = c.post("/api/register", json={"age": 22})
    assert r.status_code == 200 and r.json()["ok"] is True
    key = r.json()["profile_key"]
    assert store.get(key) == {"age": 22, "is_minor": False}


def test_register_under14_rejected(tmp_path, fake_llm_empathic):
    c, _, _ = _client(tmp_path, fake_llm_empathic)
    r = c.post("/api/register", json={"age": 13})
    assert r.status_code == 400


def test_register_minor_requires_guardian(tmp_path, fake_llm_empathic):
    c, _, _ = _client(tmp_path, fake_llm_empathic)
    assert c.post("/api/register", json={"age": 16}).status_code == 400
    r = c.post("/api/register", json={"age": 16, "guardian_contact_available": True})
    assert r.status_code == 200


def test_chat_returns_reply(tmp_path, fake_llm_empathic):
    c, store, _ = _client(tmp_path, fake_llm_empathic)
    key = c.post("/api/register", json={"age": 22}).json()["profile_key"]
    r = c.post("/api/chat", json={"profile_key": key, "text": "我今天有点累"})
    assert r.status_code == 200
    body = r.json()
    assert body["reply"] and body["risk_level"] == "none" and body["next_agent"] == "empathic"


def test_stream_sses_reply(tmp_path, fake_llm_empathic):
    c, store, _ = _client(tmp_path, fake_llm_empathic)
    key = c.post("/api/register", json={"age": 22}).json()["profile_key"]
    r = c.post("/api/chat/stream", json={"profile_key": key, "text": "你好"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert "data: " in r.text


def test_email_confirm_approve_sends(tmp_path, fake_llm_empathic):
    c, _, mailer = _client(tmp_path, fake_llm_empathic, expected_token="tok")
    r = c.post(
        "/api/email/confirm",
        json={
            "email": "u@example.com",
            "subject": "s",
            "body": "b",
            "decision": "approve",
            "confirm_token": "tok",
        },
    )
    assert r.status_code == 200 and r.json()["sent"] is True
    assert len(mailer.sent) == 1


def test_email_reject_not_sent(tmp_path, fake_llm_empathic):
    c, _, mailer = _client(tmp_path, fake_llm_empathic, expected_token="tok")
    r = c.post(
        "/api/email/confirm",
        json={
            "email": "u@example.com",
            "subject": "s",
            "body": "b",
            "decision": "reject",
            "confirm_token": "tok",
        },
    )
    assert r.status_code == 200 and r.json()["sent"] is False
    assert mailer.sent == []


def test_static_serves_soft_pastel(tmp_path, fake_llm_empathic):
    c, _, _ = _client(tmp_path, fake_llm_empathic)
    r = c.get("/web/soft-pastel/")
    assert r.status_code == 200 and "CloudMaster" in r.text


def test_static_serves_cloud_glass(tmp_path, fake_llm_empathic):
    c, _, _ = _client(tmp_path, fake_llm_empathic)
    r = c.get("/web/cloud-glass/")
    assert r.status_code == 200 and "云端陪伴" in r.text
