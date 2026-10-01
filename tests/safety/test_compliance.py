"""合规用例集（计划书 附录 A.2）——每条用例对应《人工智能拟人化互动服务管理暂行办法》义务。

纳入发布门禁：任一条失败即阻断发布。全 fake，禁触网/真实模型/真实邮件。
覆盖：注册年龄边界、未成年人模式、时长阈值（1h/2h）、AI 身份与 AIGC 标识存在性、
依赖提醒、<14 拒服务路径、未审核热线不下发、注册邮箱最小必要与可删除。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from cloudmaster.graph import build_graph
from cloudmaster.mailer import Mailer
from cloudmaster.privacy import PrivacyStore
from cloudmaster.profile_store import ProfileStore
from cloudmaster.resources import ResourceStore
from cloudmaster.review_queue import ReviewLedger
from cloudmaster.time_guard import (
    ALL_LONG_MIN,
    DEP_FREQ_THRESHOLD,
    MINOR_CLOSE_MIN,
    MINOR_PRE_MIN,
    evaluate,
)
from cloudmaster.web_app import create_app

# 合规模块整体纳入 safety 回归：`pytest -m safety` 必须覆盖合规用例集（发布门禁）。
pytestmark = pytest.mark.safety

T0 = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
TOKEN = "review-token"
MAIL = "user@example.com"


def _client(tmp_path, llm):
    app = create_app(
        graph=build_graph(llm, checkpointer=None),
        store=ProfileStore(str(tmp_path / "w.json")),
        mailer=Mailer(),
        expected_token="tok",
        reviews=ReviewLedger(str(tmp_path / "reviews.jsonl")),
        privacy=PrivacyStore(str(tmp_path / "privacy.json")),
        resources=ResourceStore(str(tmp_path / "resources.jsonl")),
        reviewer_token=TOKEN,
    )
    return TestClient(app)


# ---- TC-COMP-001 注册年龄边界：13 拒服务 / 14 可服务 / 17 未成年 / 18 成年 ----


@pytest.mark.parametrize("age", [0, 12, 13])
def test_comp_001_under14_is_refused(tmp_path, fake_llm_empathic, age):
    """《办法》未成年人保护义务：不处理不满十四周岁数据 —— 无监护人同意亦不得服务。"""
    c = _client(tmp_path, fake_llm_empathic)
    r = c.post("/api/register", json={"age": age, "email": MAIL, "guardian_contact_available": True})
    assert r.status_code == 400


def test_comp_001_age_14_accepted_with_guardian(tmp_path, fake_llm_empathic):
    c = _client(tmp_path, fake_llm_empathic)
    r = c.post("/api/register", json={"age": 14, "email": MAIL, "guardian_contact_available": True})
    assert r.status_code == 200


def test_comp_001_minor_without_guardian_signal_refused(tmp_path, fake_llm_empathic):
    """未成年人须有监护人可用信号（17 与 13 同侧边界）。"""
    c = _client(tmp_path, fake_llm_empathic)
    assert c.post("/api/register", json={"age": 17, "email": MAIL}).status_code == 400
    r = c.post("/api/register", json={"age": 17, "email": MAIL, "guardian_contact_available": True})
    assert r.status_code == 200


def test_comp_001_age_18_is_adult(tmp_path, fake_llm_empathic):
    c = _client(tmp_path, fake_llm_empathic)
    key = c.post("/api/register", json={"age": 18, "email": MAIL}).json()["profile_key"]
    assert c.get(f"/api/privacy/{key}").status_code == 200


# ---- TC-COMP-002 未成年人模式切换正确率 100% ----


@pytest.mark.parametrize(
    ("age", "expected_minor"), [(13, True), (14, True), (17, True), (18, False), (25, False)]
)
def test_comp_002_minor_mode_flag(tmp_path, fake_llm_empathic, age, expected_minor):
    c = _client(tmp_path, fake_llm_empathic)
    if age < 14:
        assert c.post("/api/register", json={"age": age, "email": MAIL}).status_code == 400
        return
    key = c.post(
        "/api/register", json={"age": age, "email": MAIL, "guardian_contact_available": age < 18}
    ).json()["profile_key"]
    export = c.get(f"/api/privacy/{key}/export").json()
    assert export["profile"]["is_minor"] is expected_minor


# ---- TC-COMP-003 时长守护阈值：未成年 1h、全员 2h ----


def test_comp_003_minor_hour_thresholds():
    assert MINOR_PRE_MIN == 50 and MINOR_CLOSE_MIN == 60
    pre = evaluate({"session_started_at": T0.isoformat()}, {"age": 16}, T0 + timedelta(minutes=50))
    close = evaluate({"session_started_at": T0.isoformat()}, {"age": 16}, T0 + timedelta(minutes=60))
    assert pre["fired"] is True and pre["messages"]
    assert close["fired"] is True and close["messages"]


def test_comp_003_adult_two_hour_threshold():
    assert ALL_LONG_MIN == 120
    before = evaluate({"session_started_at": T0.isoformat()}, {"age": 22}, T0 + timedelta(minutes=119))
    after = evaluate({"session_started_at": T0.isoformat()}, {"age": 22}, T0 + timedelta(minutes=120))
    assert before["fired"] is False
    assert after["fired"] is True


def test_comp_003_threshold_messages_are_non_threatening():
    """提醒措辞须温和、非恐吓（不得出现惩罚/禁止类措辞）。"""
    res = evaluate({"session_started_at": T0.isoformat()}, {"age": 16}, T0 + timedelta(minutes=60))
    blob = " ".join(res["messages"])
    for word in ["禁止", "违规", "强制", "锁定", "惩罚"]:
        assert word not in blob


# ---- TC-COMP-004 依赖提醒 ----


def test_comp_004_declared_dependency_prompts():
    res = evaluate({"session_started_at": T0.isoformat()}, {"age": 22, "dependency_tendency": True}, T0)
    assert res["fired"] is True
    assert any("AI 生成" in m for m in res["messages"])


def test_comp_004_observed_high_frequency_prompts():
    starts = [(T0 - timedelta(hours=1)).isoformat() for _ in range(DEP_FREQ_THRESHOLD)]
    res = evaluate({"session_started_at": T0.isoformat(), "recent_session_starts": starts}, {"age": 22}, T0)
    assert res["fired"] is True
    assert res["usage_meta"].get("dependency_observed") is True


# ---- TC-COMP-005 AI 身份与 AIGC 标识存在性 ----


def test_comp_005_ai_identity_visible_on_page(tmp_path, fake_llm_empathic):
    c = _client(tmp_path, fake_llm_empathic)
    html = c.get("/web/cloud-glass/").text
    assert "内容由 AI 生成" in html
    assert "不作心理/医疗诊断" in html


def test_comp_005_ai_disclosure_modal_present(tmp_path, fake_llm_empathic):
    c = _client(tmp_path, fake_llm_empathic)
    html = c.get("/web/cloud-glass/").text
    assert 'id="disclosure"' in html and "不是真人也不是医生" in html


# ---- TC-COMP-006 未审核热线一律不下发 ----


def test_comp_006_no_hotline_before_human_review(tmp_path, fake_llm_empathic):
    c = _client(tmp_path, fake_llm_empathic)
    body = c.get("/api/resources").json()
    assert body["hotlines"] == []
    assert "未经人工审核" in body["note"]


def test_comp_006_no_hardcoded_tel_in_frontend(tmp_path, fake_llm_empathic):
    """前端不得出现任何硬编码热线号码。"""
    c = _client(tmp_path, fake_llm_empathic)
    html = c.get("/web/cloud-glass/").text
    js = c.get("/web/common/api.js").text
    for blob in (html, js):
        assert "12356" not in blob and "010-" not in blob and "400-" not in blob


# ---- TC-COMP-007 高危不外泄：审核台须授权 ----


def test_comp_007_review_console_unauthorized_blocked(tmp_path, fake_llm_crisis_danger):
    c = _client(tmp_path, fake_llm_crisis_danger)
    key = c.post("/api/register", json={"age": 22, "email": MAIL}).json()["profile_key"]
    c.post("/api/chat", json={"profile_key": key, "text": "我不想活了"})
    assert c.get("/api/review/pending").status_code == 403
    assert c.get("/api/review/pending", params={"token": "guess"}).status_code == 403


# ---- TC-COMP-008 会话导出不含真实身份字段（邮箱属最小必要例外，须可见可删） ----


def test_comp_008_export_has_no_identity_fields(tmp_path, fake_llm_empathic):
    c = _client(tmp_path, fake_llm_empathic)
    key = c.post("/api/register", json={"age": 22, "email": MAIL}).json()["profile_key"]
    body = c.get(f"/api/privacy/{key}/export").json()
    for forbidden in ("name", "phone", "student_id", "school", "id_card"):
        assert forbidden not in body["profile"]
    # 邮箱是报告投递所必需的唯一例外，必须可查看、可删除
    assert body["profile"]["email"] == MAIL


def test_comp_008_email_removed_on_delete(tmp_path, fake_llm_empathic):
    c = _client(tmp_path, fake_llm_empathic)
    key = c.post("/api/register", json={"age": 22, "email": MAIL}).json()["profile_key"]
    assert c.delete(f"/api/profile/{key}").json()["profile_deleted"] is True
    assert c.get(f"/api/privacy/{key}/export").json()["profile"] == {}


# ---- TC-COMP-009 注册邮箱最小必要：格式校验 + 报告可退订 ----


def test_comp_009_email_required_and_validated(tmp_path, fake_llm_empathic):
    c = _client(tmp_path, fake_llm_empathic)
    assert c.post("/api/register", json={"age": 22}).status_code == 400
    assert c.post("/api/register", json={"age": 22, "email": "not-an-email"}).status_code == 400


def test_comp_009_report_opt_out_supported(tmp_path, fake_llm_empathic):
    """《办法》要求可拒绝/退订：报告默认开启，但用户可随时退订。"""
    c = _client(tmp_path, fake_llm_empathic)
    key = c.post("/api/register", json={"age": 22, "email": MAIL}).json()["profile_key"]
    assert c.get(f"/api/report/status/{key}").json()["opt_in"] is True
    assert c.post(f"/api/report/unsubscribe/{key}").json()["opt_in"] is False
    assert c.get(f"/api/report/status/{key}").json()["opt_in"] is False
