"""time_guard 图入口守卫（前置纯规则，不调用任何模型）。仅此处可写 usage_meta。

- limit_close（未成年满 1h / 全员满 2h 收尾）整轮短路，不进子 Agent；
  disclosure（依赖/AI 披露）与 reminder（50 分钟预提醒）不短路，提示照发，
  用户当轮仍得到疏导回复。
- 「当日」按 Asia/Shanghai 日历日计：跨天首条消息重置会话起点并清预提醒标记，
  当日已收尾则不重复触发、次日自然恢复。
- 本节点每轮重置 agent_hops=0（单轮防死循环语义）；L2 恢复不重跑本节点，hops 不被误清。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

MINOR_PRE_MIN = 50
MINOR_CLOSE_MIN = 60
ALL_LONG_MIN = 120

# 依赖倾向自动识别：检测「高频连续使用」。
DEP_WINDOW_HOURS = 24
DEP_FREQ_THRESHOLD = 8

# 「当日」是本地概念（用户所处的日历日），非 UTC 日。
# Asia/Shanghai 自 1991 年后无夏令时，恒为 UTC+8——用固定偏移而非 zoneinfo：
# Windows 无系统 tz 数据库，zoneinfo 需额外装 tzdata（违反零新增依赖约束），
# 固定 +8 与 IANA 库在本系统的时间范围内完全等价。
LOCAL_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai(+08:00)")

# 通知种类（turn_notices[].kind）：disclosure=AI 披露 / reminder=预提醒（均不阻断），
# limit_close=收尾（阻断）。由 SSE notice 事件下发前端。
NOTICE_DISCLOSURE = "disclosure"
NOTICE_REMINDER = "reminder"
NOTICE_LIMIT_CLOSE = "limit_close"

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


def _local_date(moment: datetime) -> str:
    return moment.astimezone(LOCAL_TZ).strftime("%Y-%m-%d")


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
    """纯规则计算。返回 {'fired', 'usage_meta', 'messages', 'notices'}。

    fired=True 仅表示命中收尾阈值（limit_close），调用方应短路（不再进子 Agent）；
    disclosure / reminder 只进 messages 与 notices，不短路。
    notices = [{"kind": disclosure|reminder|limit_close, "text": ...}]。
    """
    out_usage = dict(usage or {})
    today = _local_date(now)

    # 当日已收尾 → 不重复触发（次日自然恢复）。
    if out_usage.get("last_fired_date") == today:
        out_usage["fired"] = False
        return {"fired": False, "usage_meta": out_usage, "messages": [], "notices": []}

    # 当日会话：跨天（本地日历日）→ 重置起点并清预提醒标记。
    session_start = _parse_iso(out_usage.get("session_started_at"), now)
    if _local_date(session_start) != today:
        out_usage["session_started_at"] = now.isoformat()
        out_usage.pop("pre_warned50", None)
        session_start = now
    elif "session_started_at" not in out_usage:
        out_usage["session_started_at"] = now.isoformat()
    elapsed_min = max(0.0, (now - session_start).total_seconds() / 60.0)

    age = profile.get("age")
    is_minor = isinstance(age, int) and age < 18

    recent = _recent_starts(out_usage, now)
    out_usage["recent_session_starts"] = [m.isoformat() for m in recent]

    messages: list[str] = []
    notices: list[dict[str, str]] = []

    def _note(kind: str, text: str) -> None:
        messages.append(text)
        notices.append({"kind": kind, "text": text})

    # 依赖倾向 → AI 生成提示弹窗（非阻断）：注册自述信号，或高频连续使用的自动识别结果。
    declared = bool(profile.get("dependency_tendency"))
    observed = detect_dependency(out_usage, now)
    if (declared or observed) and not out_usage.get("disclosure_done"):
        _note(NOTICE_DISCLOSURE, DEPENDENCY_MSG if observed else AI_DISCLOSURE_MSG)
        out_usage["disclosure_done"] = True
        if observed:
            out_usage["dependency_observed"] = True

    fired = False
    if is_minor:
        if elapsed_min >= MINOR_CLOSE_MIN:
            _note(NOTICE_LIMIT_CLOSE, MINOR_CLOSE_MSG)
            out_usage["last_fired_date"] = today
            fired = True
        elif elapsed_min >= MINOR_PRE_MIN and not out_usage.get("pre_warned50"):
            _note(NOTICE_REMINDER, MINOR_PRE_MSG)
            out_usage["pre_warned50"] = True
    else:
        if elapsed_min >= ALL_LONG_MIN:
            _note(NOTICE_LIMIT_CLOSE, LONG_SESSION_MSG)
            out_usage["last_fired_date"] = today
            fired = True

    out_usage["fired"] = fired
    return {"fired": fired, "usage_meta": out_usage, "messages": messages, "notices": notices}


def time_guard_node(state: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """LangGraph 节点。now 可注入便于测试；缺省取当前 UTC。"""
    clock = now if now is not None else datetime.now(UTC)
    result = evaluate(state.get("usage_meta") or {}, state.get("user_profile") or {}, clock)
    update: dict[str, Any] = {
        "usage_meta": result["usage_meta"],
        "turn_notices": result["notices"],  # 覆盖写，无跨轮残留
        "agent_hops": 0,  # 轮生命周期锚点：重置防死循环计数
    }
    if result["messages"]:
        from langchain_core.messages import AIMessage

        update["messages"] = [AIMessage(m) for m in result["messages"]]
    return update
