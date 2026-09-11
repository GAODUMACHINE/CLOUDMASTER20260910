"""time_guard 纯规则（unit，零外部依赖）。"""

from datetime import UTC, datetime, timedelta

from cloudmaster.time_guard import AI_DISCLOSURE_MSG, evaluate

T0 = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


def test_minor_50min_pre_reminder_fires_short_circuit():
    now = T0 + timedelta(minutes=50)
    res = evaluate({"session_started_at": T0.isoformat()}, {"age": 16}, now)
    assert res["fired"] is True
    assert len(res["messages"]) == 1


def test_minor_60min_close_fires_and_sets_last_fired_date():
    now = T0 + timedelta(minutes=61)
    res = evaluate({"session_started_at": T0.isoformat()}, {"age": 15}, now)
    assert res["fired"] is True
    assert res["usage_meta"]["last_fired_date"] == "2026-09-10"


def test_same_day_not_repeated():
    now = T0 + timedelta(minutes=70)
    usage = {"session_started_at": T0.isoformat(), "last_fired_date": "2026-09-10"}
    res = evaluate(usage, {"age": 15}, now)
    assert res["fired"] is False
    assert res["messages"] == []


def test_adult_120min_reminder():
    now = T0 + timedelta(minutes=120)
    res = evaluate({"session_started_at": T0.isoformat()}, {"age": 22}, now)
    assert res["fired"] is True


def test_dependency_tendency_ai_disclosure():
    now = T0 + timedelta(minutes=5)
    res = evaluate({"session_started_at": T0.isoformat()}, {"age": 22, "dependency_tendency": True}, now)
    assert res["fired"] is True
    assert AI_DISCLOSURE_MSG in res["messages"]


def test_below_threshold_not_fired():
    now = T0 + timedelta(minutes=10)
    res = evaluate({"session_started_at": T0.isoformat()}, {"age": 16}, now)
    assert res["fired"] is False
