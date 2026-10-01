"""单元：疏导报告生成（ADR-009）——只含聚合信息与建议，绝不落用户原话。"""

from __future__ import annotations

from datetime import UTC, datetime

from langchain_core.messages import AIMessage, HumanMessage

from cloudmaster.report import DISCLAIMER, build_report, new_report_id


def _msgs():
    return [HumanMessage("我最近很难过"), AIMessage("我在这里陪你"), HumanMessage("谢谢")]


def test_report_id_shape():
    rid = new_report_id()
    assert rid.startswith("RP-") and len(rid) > 6


def test_report_counts_turns():
    r = build_report(profile_key="anon-1", profile={"age": 22}, messages=_msgs())
    assert r["user_turns"] == 2 and r["ai_turns"] == 1


def test_report_never_contains_raw_conversation():
    """隐私硬约束：报告不含用户原话。"""
    r = build_report(profile_key="anon-1", profile={"age": 22}, messages=_msgs())
    assert r["contains_raw_conversation"] is False
    assert "我最近很难过" not in r["body"]
    assert "谢谢" not in r["body"]


def test_report_lists_sources_only():
    r = build_report(
        profile_key="anon-1",
        profile={"age": 22},
        messages=_msgs(),
        citations=[{"source": "科普库 v1", "text": "不该出现的片段"}, {"source": "科普库 v1"}],
    )
    assert r["sources"] == ["科普库 v1"]  # 去重
    assert "不该出现的片段" not in r["body"]


def test_report_always_carries_disclaimer():
    r = build_report(profile_key="anon-1", profile={"age": 22}, messages=_msgs())
    assert r["disclaimer"] == DISCLAIMER
    assert DISCLAIMER in r["body"]
    assert "不构成" in r["body"]


def test_report_subject_contains_id_for_reply_linking():
    r = build_report(profile_key="anon-1", profile={"age": 22}, messages=_msgs())
    assert f"[{r['report_id']}]" in r["subject"]


def test_report_marks_guard_events_without_detail():
    r = build_report(
        profile_key="anon-1",
        profile={"age": 22},
        messages=_msgs(),
        usage_meta={"last_fired_date": "2026-09-17"},
    )
    assert r["risk_level"] == "low"
    assert "已有提醒触发" in r["body"]


def test_report_has_emergency_guidance():
    r = build_report(profile_key="anon-1", profile={"age": 22}, messages=_msgs())
    assert "急救" in r["body"]


def test_report_empty_conversation_is_safe():
    r = build_report(profile_key="anon-1", profile={}, messages=[], now=datetime(2026, 9, 17, tzinfo=UTC))
    assert r["user_turns"] == 0 and r["ai_turns"] == 0
    assert r["sources"] == []
    assert r["body"]
