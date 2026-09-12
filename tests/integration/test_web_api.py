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


def test_static_serves_cloud_glass(tmp_path, fake_llm_empathic):
    c, _, _ = _client(tmp_path, fake_llm_empathic)
    r = c.get("/web/cloud-glass/")
    assert r.status_code == 200
    # 品牌标题（大标题 + 页面 title）锁定为「CloudMaster · 云上高士」
    assert '<h1 class="brand">CloudMaster<span class="dot"> · </span>云上高士</h1>' in r.text
    assert "<title>CloudMaster · 云上高士</title>" in r.text


def test_register_invalid_body_is_422(tmp_path, fake_llm_empathic):
    # 无效/缺字段的注册体返回 422(校验)而非 400；detail 为数组，前端须渲染为可读文本(不得 [object Object])
    c, _, _ = _client(tmp_path, fake_llm_empathic)
    r = c.post("/api/register", json={"age": "abc"})
    assert r.status_code == 422 and isinstance(r.json()["detail"], list)


# ---- v1.1.0：匿名 ID 隔离 + 退出/申诉/资源入口 ----


def _full_client(tmp_path, llm, token="tok"):
    """带 checkpointer 与临时申诉台账的完整客户端（全部落在 tmp_path，不污染仓库 data/）。"""
    from langgraph.checkpoint.memory import InMemorySaver

    from cloudmaster.appeals import AppealStore

    graph = build_graph(llm, checkpointer=InMemorySaver())
    store = ProfileStore(str(tmp_path / "s.json"))
    appeals = AppealStore(str(tmp_path / "appeals.jsonl"))
    app = create_app(
        graph=graph,
        store=store,
        mailer=Mailer(),
        expected_token=token,
        appeals=appeals,
    )
    return TestClient(app), store, appeals, graph


def test_register_same_age_gets_distinct_keys(tmp_path, fake_llm_empathic):
    """同年龄两次注册必须是不同匿名 ID（旧 hash(age) 实现会复用同一 ID）。"""
    c, store, _, _ = _full_client(tmp_path, fake_llm_empathic)
    k1 = c.post("/api/register", json={"age": 22}).json()["profile_key"]
    k2 = c.post("/api/register", json={"age": 22}).json()["profile_key"]
    assert k1 != k2
    assert store.get(k1) == {"age": 22, "is_minor": False}
    assert store.get(k2) == {"age": 22, "is_minor": False}


def test_same_age_sessions_are_isolated(tmp_path, fake_llm_empathic):
    """同龄用户不得共用会话 thread（串会话 = 用户数据越权）。"""
    c, _, _, graph = _full_client(tmp_path, fake_llm_empathic)
    k1 = c.post("/api/register", json={"age": 22}).json()["profile_key"]
    k2 = c.post("/api/register", json={"age": 22}).json()["profile_key"]
    c.post("/api/chat", json={"profile_key": k1, "text": "我今天有点累"})
    assert graph.get_state({"configurable": {"thread_id": k1}}).values
    assert not graph.get_state({"configurable": {"thread_id": k2}}).values


def test_delete_profile_clears_profile_and_thread(tmp_path, fake_llm_empathic):
    """TC-PRIV-004：便捷退出/删除——最小画像与 thread 数据一并清除。"""
    c, store, _, graph = _full_client(tmp_path, fake_llm_empathic)
    key = c.post("/api/register", json={"age": 22}).json()["profile_key"]
    c.post("/api/chat", json={"profile_key": key, "text": "我今天有点累"})
    r = c.delete(f"/api/profile/{key}")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "profile_deleted": True, "thread_deleted": True}
    assert store.get(key) is None
    assert not graph.get_state({"configurable": {"thread_id": key}}).values
    # 幂等：重复删除仍返回成功，且不因状态码泄露「该匿名标识是否存在」（防枚举）
    again = c.delete(f"/api/profile/{key}")
    assert again.status_code == 200 and again.json()["profile_deleted"] is False


def test_appeal_submits_ticket(tmp_path, fake_llm_empathic):
    """TC-PRIV-006：申诉入口闭环，返回可追踪工单号。"""
    c, _, appeals, _ = _full_client(tmp_path, fake_llm_empathic)
    r = c.post(
        "/api/appeal",
        json={
            "kind": "minor_misjudged",
            "text": "我满 18 岁了但被判定为未成年模式",
            "profile_key": "anon-x",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["ticket_id"].startswith("AP-") and body["submitted_at"]
    assert appeals.count() == 1


def test_appeal_rejects_empty_text_and_bad_kind(tmp_path, fake_llm_empathic):
    c, _, appeals, _ = _full_client(tmp_path, fake_llm_empathic)
    assert c.post("/api/appeal", json={"kind": "other", "text": "  "}).status_code == 400
    assert c.post("/api/appeal", json={"kind": "nope", "text": "内容"}).status_code == 400
    assert appeals.count() == 0


def test_resources_page_has_appeal_entry_and_no_hotline_digits(tmp_path, fake_llm_empathic):
    """TC-RES-002：资源页含申诉入口；红线：不硬编码任何热线号码。"""
    import re

    c, _, _, _ = _full_client(tmp_path, fake_llm_empathic)
    r = c.get("/api/resources")
    assert r.status_code == 200
    body = r.json()
    assert body["appeals"]["submit_url"] == "/api/appeal"
    assert len(body["entries"]) >= 3
    assert not re.search(r"\d{3,}", r.text), "资源页不得出现疑似热线号码的数字串"
