"""time_guard 图入口守卫（前置纯规则，不调用任何模型）。

仅此处可写 usage_meta（ADR-001）。命中阈值 → 提醒写入 messages 并短路返回（不进子 Agent）。
依赖倾向弹窗提示「内容由 AI 生成」。当日已收尾不重复触发，次日恢复。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

MINOR_PRE_MIN = 50
MINOR_CLOSE_MIN = 60
ALL_LONG_MIN = 120

# 依赖倾向自动识别（计划书 3.1.3 第 10 条：检测「高频连续使用」）。
DEP_WINDOW_HOURS = 24
DEP_FREQ_THRESHOLD = 8

AI_DISCLOSURE_MSG = "💡 依赖提示：这段内容由 AI 生成，仅供参考，不构成专业诊断或建议。"
MINOR_PRE_MSG = "小提醒：本次陪伴已约 50 分钟，休息一下会更好，随时可以回来。"
MINOR_CLOSE_MSG = "今晚已陪伴满 1 小时，先到这里好好休息吧。明天我们继续。"
LONG_SESSION_MSG = "已陪伴满 2 小时，建议起身放松一下。随时可以继续聊。"
DEPENDENCY_MSG = (
    "💡 依赖提示：这段内容由 AI 生成。最近你来得比较频繁，我很愿意陪你，"
    "但也想提醒你——出去走走、和身边的人说说话，或者找线下支持，同样重要。"
)


def _parse_iso(value: str | None, fallback: datetime) -> datetime:
    if not value:
        return fallback
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return fallback


def _recent_starts(usage: dict[str, Any], now: datetime) -> list[datetime]:
    """取最近 DEP_WINDOW_HOURS 内的会话开始时刻（含本轮），越窗的旧记录自动淘汰。"""
    cutoff = now - timedelta(hours=DEP_WINDOW_HOURS)
    raw = list(usage.get("recent_session_starts") or [])
    raw.append(now.isoformat())
    kept: list[datetime] = []
    for item in raw:
        moment = _parse_iso(item if isinstance(item, str) else None, now)
        if moment >= cutoff:
            kept.append(moment)
    return kept


def detect_dependency(usage: dict[str, Any], now: datetime) -> bool:
    """高频连续使用识别：近 24h 内会话次数达阈值即视为有依赖倾向。纯规则。"""
    return len(_recent_starts(usage, now)) >= DEP_FREQ_THRESHOLD


def evaluate(usage: dict[str, Any], profile: dict[str, Any], now: datetime) -> dict[str, Any]:
    """纯规则计算。返回 {'fired', 'usage_meta', 'messages'}。

    fired=True 表示本轮命中阈值，调用方应短路（不再进子 Agent）。
    """
    out_usage = dict(usage or {})
    if "session_started_at" not in out_usage:
        out_usage["session_started_at"] = now.isoformat()

    age = profile.get("age")
    is_minor = isinstance(age, int) and age < 18
    session_start = _parse_iso(out_usage.get("session_started_at"), now)
    elapsed_min = max(0.0, (now - session_start).total_seconds() / 60.0)
    today = now.strftime("%Y-%m-%d")

    recent = _recent_starts(out_usage, now)
    out_usage["recent_session_starts"] = [m.isoformat() for m in recent]

    messages: list[str] = []
    fired = False

    # 当日已收尾 → 不重复触发（次日恢复）。
    if out_usage.get("last_fired_date") == today:
        out_usage["fired"] = False
        return {"fired": False, "usage_meta": out_usage, "messages": []}

    # 依赖倾向 → AI 生成提示弹窗：注册自述信号，或高频连续使用的自动识别结果。
    declared = bool(profile.get("dependency_tendency"))
    observed = detect_dependency(out_usage, now)
    if (declared or observed) and not out_usage.get("disclosure_done"):
        messages.append(DEPENDENCY_MSG if observed else AI_DISCLOSURE_MSG)
        out_usage["disclosure_done"] = True
        if observed:
            out_usage["dependency_observed"] = True

    if is_minor:
        if elapsed_min >= MINOR_CLOSE_MIN:
            messages.append(MINOR_CLOSE_MSG)
            out_usage["last_fired_date"] = today
        elif elapsed_min >= MINOR_PRE_MIN and not out_usage.get("pre_warned50"):
            messages.append(MINOR_PRE_MSG)
            out_usage["pre_warned50"] = True
    else:
        if elapsed_min >= ALL_LONG_MIN:
            messages.append(LONG_SESSION_MSG)
            out_usage["last_fired_date"] = today

    fired = bool(messages)
    out_usage["fired"] = fired
    return {"fired": fired, "usage_meta": out_usage, "messages": messages}


def time_guard_node(state: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """LangGraph 节点。now 可注入便于测试；缺省取当前 UTC。"""
    clock = now if now is not None else datetime.now(UTC)
    result = evaluate(state.get("usage_meta") or {}, state.get("user_profile") or {}, clock)
    update: dict[str, Any] = {"usage_meta": result["usage_meta"]}
    if result["messages"]:
        from langchain_core.messages import AIMessage

        update["messages"] = [AIMessage(m) for m in result["messages"]]
    return update
