"""疏导报告生成（ADR-009，计划书 3.1.3 / P1「阶段性总结经用户确认后发送」）。

隐私设计：报告**只含聚合信息与建议**，不含用户原话：
- 会话轮次、开始/结束时间、风险分级分布、引用来源标题、时长守护触发情况；
- 显式附「不构成诊断」声明与数据说明（发了什么、依据什么）；
- 报告编号 `RP-xxxxxx` 写入主题，作为收信侧回信归属依据。
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any

DISCLAIMER = (
    "本报告由 AI 依据你的会话聚合信息自动生成，仅供自我觉察参考，"
    "不构成任何诊断、治疗或用药建议；如需专业判断请咨询心理专业人员。"
)

RISK_LABELS = {"none": "平稳", "low": "需要留意", "high": "已升级人工审核"}


def new_report_id() -> str:
    return "RP-" + secrets.token_hex(6)


def _as_text(item: Any) -> str:
    return str(getattr(item, "content", item) or "")


def build_report(
    *,
    profile_key: str,
    profile: dict[str, Any] | None,
    messages: list[Any] | None,
    citations: list[dict[str, Any]] | None = None,
    usage_meta: dict[str, Any] | None = None,
    report_id: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """由会话状态生成报告草稿（纯函数，便于离线单测）。"""
    moment = now or datetime.now(UTC)
    msgs = list(messages or [])
    user_turns = sum(1 for m in msgs if getattr(m, "type", "") == "human")
    ai_turns = sum(1 for m in msgs if getattr(m, "type", "") == "ai")
    usage = usage_meta or {}

    risk = "none"
    if usage.get("last_fired_date"):
        risk = "low"
    if usage.get("dependency_observed"):
        risk = "low"

    sources: list[str] = []
    for c in citations or []:
        src = str(c.get("source") or "").strip()
        if src and src not in sources:
            sources.append(src)

    rid = report_id or new_report_id()
    lines = [
        "你好，这是你这一阶段的疏导小结。",
        "",
        "一、会话概况",
        f"- 你的发言：{user_turns} 次；陪伴回复：{ai_turns} 次",
        f"- 报告生成时间：{moment.strftime('%Y-%m-%d %H:%M')}（UTC）",
        "",
        "二、状态与守护",
        f"- 当前风险分级：{RISK_LABELS.get(risk, '平稳')}",
        f"- 使用时长守护：{'本阶段已有提醒触发' if usage.get('last_fired_date') else '本阶段未触发'}",
        "",
        "三、你了解过的心理科普主题（仅列来源）",
    ]
    if sources:
        lines.extend(f"- {s}" for s in sources)
    else:
        lines.append("- 本阶段未产生知识库引用记录")
    lines += [
        "",
        "四、给你的建议",
        "- 保持规律作息与适度运动，这对情绪稳定帮助最大；",
        "- 若持续低落、失眠或影响学习生活，建议预约学校心理中心或专业咨询；",
        "- 如果出现伤害自己的想法，请立即拨打当地急救电话或前往就近医院急诊，并告诉可信任的人。",
        "",
        "五、说明",
        "- 本报告不含你的对话原文，只含聚合信息与建议；",
        "- 你可随时在「设置与资源」中退订报告或删除全部数据。",
        "",
        DISCLAIMER,
    ]
    body = "\n".join(lines)
    return {
        "report_id": rid,
        "profile_key": profile_key,
        "generated_at": moment.isoformat(),
        "user_turns": user_turns,
        "ai_turns": ai_turns,
        "risk_level": risk,
        "risk_label": RISK_LABELS.get(risk, "平稳"),
        "sources": sources,
        "subject": f"[{rid}] 你的阶段性疏导报告（CloudMaster 云上高士）",
        "body": body,
        "disclaimer": DISCLAIMER,
        "contains_raw_conversation": False,
    }
