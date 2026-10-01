"""集成：人工审核台闭环 + 自评 + 隐私保留期/导出 + 已审核资源（全 fake，禁触网）。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from cloudmaster.graph import build_graph
from cloudmaster.mailer import Mailer
from cloudmaster.privacy import PrivacyStore
from cloudmaster.profile_store import ProfileStore
from cloudmaster.resources import ResourceStore
from cloudmaster.review_queue import ReviewLedger
from cloudmaster.web_app import create_app

TOKEN = "review-token"


def _client(tmp_path, llm, *, token=TOKEN):
    store = ProfileStore(str(tmp_path / "w.json"))
    app = create_app(
        graph=build_graph(llm, checkpointer=None),
        store=store,
        mailer=Mailer(),
        expected_token="tok",
        reviews=ReviewLedger(str(tmp_path / "reviews.jsonl")),
        privacy=PrivacyStore(str(tmp_path / "privacy.json")),
        resources=ResourceStore(str(tmp_path / "resources.jsonl")),
        reviewer_token=token,
    )
    return TestClient(app), store


def _register(client, age=22, **extra):
    return client.post("/api/register", json={"age": age, "email": "u@example.com", **extra}).json()[
        "profile_key"
    ]


# ---------- L2 → 审核台闭环 ----------


def test_l2_chat_opens_review_case(tmp_path, fake_llm_crisis_danger):
    c, _ = _client(tmp_path, fake_llm_crisis_danger)
    key = _register(c)
    r = c.post("/api/chat", json={"profile_key": key, "text": "我不想活了，想自杀"})
    assert r.status_code == 200
    body = r.json()
    assert body["risk_level"] == "high"
    assert body["escalation"] and body["escalation"]["ticket_id"].startswith("HR-")


def test_normal_chat_creates_no_review_case(tmp_path, fake_llm_empathic):
    c, _ = _client(tmp_path, fake_llm_empathic)
    key = _register(c)
    body = c.post("/api/chat", json={"profile_key": key, "text": "今天有点累"}).json()
    assert body["risk_level"] == "none" and body["escalation"] is None
    assert c.get("/api/review/pending", params={"token": TOKEN}).json()["count"] == 0


def test_review_console_requires_token(tmp_path, fake_llm_crisis_danger):
    c, _ = _client(tmp_path, fake_llm_crisis_danger)
    assert c.get("/api/review/pending").status_code == 403
    assert c.get("/api/review/pending", params={"token": "wrong"}).status_code == 403
    assert c.get("/api/review/pending", params={"token": TOKEN}).status_code == 200


def test_review_console_disabled_without_configured_token(tmp_path, fake_llm_empathic):
    """未配置审核令牌时必须拒绝开放（最小暴露），而不是默认放行。"""
    c, _ = _client(tmp_path, fake_llm_empathic, token="")
    assert c.get("/api/review/pending", params={"token": ""}).status_code == 403
    assert c.get("/api/review/pending", params={"token": "anything"}).status_code == 403


def test_review_approve_closes_case_with_audit_and_followup(tmp_path, fake_llm_crisis_danger):
    c, _ = _client(tmp_path, fake_llm_crisis_danger)
    key = _register(c)
    ticket = c.post("/api/chat", json={"profile_key": key, "text": "我不想活了"}).json()["escalation"][
        "ticket_id"
    ]

    pending = c.get("/api/review/pending", params={"token": TOKEN}).json()
    assert pending["count"] == 1 and pending["pending"][0]["ticket_id"] == ticket
    assert set(pending["decisions"]) == {"approve", "block"}
    assert "guardian" in pending["contact_kinds"]

    detail = c.get(f"/api/review/{ticket}", params={"token": TOKEN}).json()
    assert detail["case"]["basis_level"] == "L2"
    assert detail["context"], "审核台应能看到上下文"

    r = c.post(
        "/api/review/decision",
        params={"token": TOKEN},
        json={"ticket_id": ticket, "decision": "approve", "reviewer": "A1", "contact_kind": "guardian"},
    )
    assert r.status_code == 200
    out = r.json()
    assert out["ok"] and out["pending"] == 0
    assert out["audit_log"] and out["audit_log"][0]["decision"] == "approve"
    assert out["contact_log"] and out["next_followup"]
    assert c.get("/api/review/pending", params={"token": TOKEN}).json()["count"] == 0


def test_review_block_records_audit_only(tmp_path, fake_llm_crisis_danger):
    c, _ = _client(tmp_path, fake_llm_crisis_danger)
    key = _register(c)
    ticket = c.post("/api/chat", json={"profile_key": key, "text": "我不想活了"}).json()["escalation"][
        "ticket_id"
    ]
    out = c.post(
        "/api/review/decision",
        params={"token": TOKEN},
        json={"ticket_id": ticket, "decision": "block", "reviewer": "A1", "contact_kind": "none"},
    ).json()
    assert out["audit_log"] and not out["contact_log"] and out["next_followup"] is None


def test_review_decision_rejects_unknown_and_double(tmp_path, fake_llm_crisis_danger):
    c, _ = _client(tmp_path, fake_llm_crisis_danger)
    key = _register(c)
    ticket = c.post("/api/chat", json={"profile_key": key, "text": "我不想活了"}).json()["escalation"][
        "ticket_id"
    ]
    assert (
        c.post(
            "/api/review/decision",
            params={"token": TOKEN},
            json={"ticket_id": "HR-nope", "decision": "approve"},
        ).status_code
        == 404
    )
    assert (
        c.post("/api/review/decision", params={"token": TOKEN}, json={"decision": "approve"}).status_code
        == 400
    )
    c.post(
        "/api/review/decision",
        params={"token": TOKEN},
        json={"ticket_id": ticket, "decision": "approve"},
    )
    assert (
        c.post(
            "/api/review/decision", params={"token": TOKEN}, json={"ticket_id": ticket, "decision": "block"}
        ).status_code
        == 404
    )
    assert c.get(f"/api/review/{ticket}", params={"token": TOKEN}).status_code == 404


def test_review_decision_requires_token(tmp_path, fake_llm_crisis_danger):
    c, _ = _client(tmp_path, fake_llm_crisis_danger)
    key = _register(c)
    ticket = c.post("/api/chat", json={"profile_key": key, "text": "我不想活了"}).json()["escalation"][
        "ticket_id"
    ]
    assert (
        c.post("/api/review/decision", json={"ticket_id": ticket, "decision": "approve"}).status_code == 403
    )
    assert (
        c.post(
            "/api/review/decision",
            params={"token": "wrong"},
            json={"ticket_id": ticket, "decision": "approve"},
        ).status_code
        == 403
    )


# ---------- 情绪自评 ----------


def test_assessment_items_shape(tmp_path, fake_llm_empathic):
    c, _ = _client(tmp_path, fake_llm_empathic)
    body = c.get("/api/assessment/items").json()
    assert len(body["items"]) == 4
    assert [o["value"] for o in body["choices"]] == ["none", "rare", "often", "always"]
    assert body["disclaimer"]


def test_assessment_normal_band_creates_no_case(tmp_path, fake_llm_empathic):
    c, _ = _client(tmp_path, fake_llm_empathic)
    body = c.post(
        "/api/assessment", json={"answers": {k: "rare" for k in ("mood", "sleep", "anxiety", "function")}}
    ).json()
    assert body["band"] == "需要留意" and body["urgent"] is False
    assert c.get("/api/review/pending", params={"token": TOKEN}).json()["count"] == 0


def test_assessment_urgent_escalates_to_review_console(tmp_path, fake_llm_empathic):
    c, _ = _client(tmp_path, fake_llm_empathic)
    body = c.post(
        "/api/assessment", json={"answers": {k: "always" for k in ("mood", "sleep", "anxiety", "function")}}
    ).json()
    assert body["urgent"] is True
    pending = c.get("/api/review/pending", params={"token": TOKEN}).json()
    assert pending["count"] == 1
    assert pending["pending"][0]["basis_level"] == "self-assessment"


def test_assessment_invalid_payload_400(tmp_path, fake_llm_empathic):
    c, _ = _client(tmp_path, fake_llm_empathic)
    assert c.post("/api/assessment", json={"answers": {}}).status_code == 400


# ---------- 隐私：保留期 / 导出 / 删除 ----------


def test_privacy_default_retention_and_choices(tmp_path, fake_llm_empathic):
    c, _ = _client(tmp_path, fake_llm_empathic)
    key = _register(c)
    body = c.get(f"/api/privacy/{key}").json()
    assert body["retention"]["retention_days"] == 30
    assert body["choices"] == [7, 30, 90]
    assert body["purge"]["delete_after"]


def test_privacy_retention_update_and_reject(tmp_path, fake_llm_empathic):
    c, _ = _client(tmp_path, fake_llm_empathic)
    key = _register(c)
    ok = c.post(f"/api/privacy/{key}/retention", json={"days": 90})
    assert ok.status_code == 200 and ok.json()["retention"]["retention_days"] == 90
    assert c.post(f"/api/privacy/{key}/retention", json={"days": 45}).status_code == 400


def test_privacy_export_contains_only_own_minimal_profile(tmp_path, fake_llm_crisis_danger):
    c, _ = _client(tmp_path, fake_llm_crisis_danger)
    key = _register(c)
    c.post("/api/chat", json={"profile_key": key, "text": "你好"})
    body = c.get(f"/api/privacy/{key}/export").json()
    assert body["profile_key"] == key
    assert body["profile"]["age"] == 22 and body["profile"]["email"] == "u@example.com"
    assert body["message_count"] >= 1
    assert set(body["profile"]) <= {
        "age",
        "is_minor",
        "guardian_contact_available",
        "dependency_tendency",
        "email",
        "report_opt_in",
    }
    assert "note" in body


def test_delete_profile_also_clears_retention(tmp_path, fake_llm_empathic):
    c, _ = _client(tmp_path, fake_llm_empathic)
    key = _register(c)
    c.post(f"/api/privacy/{key}/retention", json={"days": 7})
    assert c.delete(f"/api/profile/{key}").json()["ok"] is True
    assert c.get(f"/api/privacy/{key}").json()["retention"]["retention_days"] == 30


# ---------- 已审核资源 ----------


def test_resources_default_downloads_no_hotline(tmp_path, fake_llm_empathic):
    c, _ = _client(tmp_path, fake_llm_empathic)
    body = c.get("/api/resources").json()
    assert body["hotlines"] == []
    assert "未经人工审核" in body["note"]
    assert body["entries"] and body["appeals"]["kinds"]


def test_hotline_registration_requires_token_and_reviewer(tmp_path, fake_llm_empathic):
    c, _ = _client(tmp_path, fake_llm_empathic)
    payload = {"title": "某市心理援助热线", "tel": "010-12345678", "reviewer": "A1", "kind": "hotline"}
    assert c.post("/api/resources/hotline", json=payload).status_code == 403
    assert c.post("/api/resources/hotline", params={"token": "wrong"}, json=payload).status_code == 403
    assert c.get("/api/resources").json()["hotlines"] == []

    ok = c.post("/api/resources/hotline", params={"token": TOKEN}, json=payload)
    assert ok.status_code == 200
    approved = c.get("/api/resources").json()["hotlines"]
    assert len(approved) == 1 and approved[0]["tel"] == "010-12345678"

    bad = c.post("/api/resources/hotline", params={"token": TOKEN}, json={**payload, "reviewer": ""})
    assert bad.status_code == 400


# ---------- 中断态语义（v1.4.0）：挂起占位 / 不可绕过 / 孤儿工单 ----------


def test_l2_chat_returns_hold_notice_not_user_echo(tmp_path, fake_llm_crisis_danger):
    """L2 停在 human_review 中断点时，不得把用户原话当「AI 回复」回显。"""
    c, _ = _client(tmp_path, fake_llm_crisis_danger)
    key = _register(c)
    body = c.post("/api/chat", json={"profile_key": key, "text": "我不想活了"}).json()
    assert body["risk_level"] == "high"
    assert body["held_for_review"] is True
    assert body["reply"] != "我不想活了", "中断态下回显了用户原话"
    assert "人工审核" in body["reply"]
    assert body["escalation"]["ticket_id"].startswith("HR-")


def test_non_crisis_message_while_pending_cannot_bypass_review(tmp_path, fake_llm_crisis_danger):
    """待审期间发一条非危机消息不得绕过人工审核：不生成自动回复、工单不失效。"""
    c, _ = _client(tmp_path, fake_llm_crisis_danger)
    key = _register(c)
    c.post("/api/chat", json={"profile_key": key, "text": "我不想活了"})

    again = c.post("/api/chat", json={"profile_key": key, "text": "我先去吃饭了"}).json()
    assert again["held_for_review"] is True
    assert again["reply"] != "我先去吃饭了"

    pending = c.get("/api/review/pending", params={"token": TOKEN}).json()
    assert pending["count"] == 1, "挂起期间不得重复登记工单"
    ticket = pending["pending"][0]["ticket_id"]

    detail = c.get(f"/api/review/{ticket}", params={"token": TOKEN}).json()
    assert any(m["text"] == "我先去吃饭了" for m in detail["context"]), "挂起期间的消息仍须留痕供审核"

    ok = c.post(
        "/api/review/decision",
        params={"token": TOKEN},
        json={"ticket_id": ticket, "decision": "approve", "reviewer": "A1"},
    )
    assert ok.status_code == 200, "挂起态被绕过，工单已失效"


def test_review_decision_on_orphan_case_conflicts(tmp_path, fake_llm_crisis_danger):
    """会话已删除时裁决必须 409，且不得把台账闭环（禁止静默成功）。"""
    c, _ = _client(tmp_path, fake_llm_crisis_danger)
    key = _register(c)
    ticket = c.post("/api/chat", json={"profile_key": key, "text": "我不想活了"}).json()["escalation"][
        "ticket_id"
    ]
    assert c.delete(f"/api/profile/{key}").json()["ok"] is True

    r = c.post(
        "/api/review/decision", params={"token": TOKEN}, json={"ticket_id": ticket, "decision": "approve"}
    )
    assert r.status_code == 409
    assert "会话" in r.json()["detail"]
    assert c.get("/api/review/pending", params={"token": TOKEN}).json()["count"] == 1, "台账被静默闭环"


# ---------- 审核台值班界面（静态页） ----------


def test_review_console_page_served(tmp_path, fake_llm_empathic):
    c, _ = _client(tmp_path, fake_llm_empathic)
    r = c.get("/web/review/")
    assert r.status_code == 200
    assert "人工审核台" in r.text
    assert "值班鉴权" in r.text
    assert "待审队列" in r.text


def test_review_console_page_keeps_no_secret_or_hotline(tmp_path, fake_llm_empathic):
    """值班页不得内置任何令牌字面量，也不得出现疑似热线号码。"""
    import re

    c, _ = _client(tmp_path, fake_llm_empathic)
    text = c.get("/web/review/").text
    assert TOKEN not in text
    assert "review-token" not in text
    assert not re.search(r"\d{3,}", text), "值班页不得出现疑似热线号码的数字串"
