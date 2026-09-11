"""time_guard 图入口守卫（前置纯规则，不调用任何模型）。

仅此处可写 usage_meta（ADR-001）。命中阈值 → 提醒写入 messages 并短路返回（不进子 Agent）。
依赖倾向弹窗提示「内容由 AI 生成」。当日已收尾不重复触发，次日恢复。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

MINOR_PRE_MIN = 50
MINOR_CLOSE_MIN = 60
ALL_LONG_MIN = 120

AI_DISCLOSURE_MSG = "💡 依赖提示：这段内容由 AI 生成，仅供参考，不构成专业诊断或建议。"
MINOR_PRE_MSG = "小提醒：本次陪伴已约 50 分钟，休息一下会更好，随时可以回来。"
MINOR_CLOSE_MSG = "今晚已陪伴满 1 小时，先到这里好好休息吧。明天我们继续。"
LONG_SESSION_MSG = "已陪伴满 2 小时，建议起身放松一下。随时可以继续聊。"


def _parse_iso(value: str | None, fallback: datetime) -> datetime:
    if not value:
        return fallback
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return fallback


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

    messages: list[str] = []
    fired = False

    # 当日已收尾 → 不重复触发（次日恢复）。
    if out_usage.get("last_fired_date") == today:
        out_usage["fired"] = False
        return {"fired": False, "usage_meta": out_usage, "messages": []}

    # 依赖倾向 → AI 生成提示弹窗。
    if profile.get("dependency_tendency") and not out_usage.get("disclosure_done"):
        messages.append(AI_DISCLOSURE_MSG)
        out_usage["disclosure_done"] = True

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
