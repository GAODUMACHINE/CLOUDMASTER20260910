"""time_guard 纯规则（unit，零外部依赖）。"""

from datetime import UTC, datetime, timedelta

from lightcloudmaster.time_guard import (
    AI_DISCLOSURE_MSG,
    DEP_FREQ_THRESHOLD,
    DEPENDENCY_MSG,
    detect_dependency,
    evaluate,
)

T0 = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


def test_minor_50min_pre_reminder_non_blocking():
    """v2.0.0 P2：50 分钟预提醒为 reminder（非阻断）——提示照发但用户当轮仍有疏导回复。"""
    now = T0 + timedelta(minutes=50)
    res = evaluate({"session_started_at": T0.isoformat()}, {"age": 16}, now)
    assert res["fired"] is False
    assert len(res["messages"]) == 1
    assert res["notices"] == [{"kind": "reminder", "text": res["messages"][0]}]


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
    """v2.0.0 P2：依赖披露为 disclosure（非阻断）——弹窗语义，不吞掉当轮疏导回复。"""
    now = T0 + timedelta(minutes=5)
    res = evaluate({"session_started_at": T0.isoformat()}, {"age": 22, "dependency_tendency": True}, now)
    assert res["fired"] is False
    assert AI_DISCLOSURE_MSG in res["messages"]
    assert res["notices"][0]["kind"] == "disclosure"


def test_below_threshold_not_fired():
    now = T0 + timedelta(minutes=10)
    res = evaluate({"session_started_at": T0.isoformat()}, {"age": 16}, now)
    assert res["fired"] is False


# ---- 依赖倾向自动识别（计划书 3.1.3-10：检测高频连续使用） ----


def test_detect_dependency_below_threshold():
    now = T0
    starts = [(now - timedelta(hours=i)).isoformat() for i in range(1, 4)]
    assert detect_dependency({"recent_session_starts": starts}, now) is False


def test_detect_dependency_at_threshold():
    now = T0
    starts = [(now - timedelta(hours=i)).isoformat() for i in range(1, DEP_FREQ_THRESHOLD)]
    assert detect_dependency({"recent_session_starts": starts}, now) is True


def test_detect_dependency_ignores_starts_outside_window():
    now = T0
    stale = [(now - timedelta(hours=30 + i)).isoformat() for i in range(20)]
    assert detect_dependency({"recent_session_starts": stale}, now) is False


def test_observed_dependency_prompts_and_flags():
    """未自述依赖倾向，但高频使用 → 仍应提示并标记观察结果（v2.0.0 P2：非阻断）。"""
    now = T0
    starts = [(now - timedelta(hours=1)).isoformat() for _ in range(DEP_FREQ_THRESHOLD)]
    res = evaluate({"session_started_at": now.isoformat(), "recent_session_starts": starts}, {"age": 22}, now)
    assert res["fired"] is False
    assert DEPENDENCY_MSG in res["messages"]
    assert res["usage_meta"]["dependency_observed"] is True
    assert res["usage_meta"]["disclosure_done"] is True


def test_dependency_not_repeated_in_same_session():
    now = T0
    starts = [(now - timedelta(hours=1)).isoformat() for _ in range(DEP_FREQ_THRESHOLD)]
    usage = {
        "session_started_at": now.isoformat(),
        "recent_session_starts": starts,
        "disclosure_done": True,
    }
    res = evaluate(usage, {"age": 22, "dependency_tendency": True}, now)
    assert DEPENDENCY_MSG not in res["messages"]


def test_recent_starts_are_trimmed_to_window():
    now = T0
    stale = [(now - timedelta(hours=40 + i)).isoformat() for i in range(10)]
    res = evaluate({"session_started_at": now.isoformat(), "recent_session_starts": stale}, {"age": 22}, now)
    kept = res["usage_meta"]["recent_session_starts"]
    assert len(kept) == 1  # 仅保留本轮
