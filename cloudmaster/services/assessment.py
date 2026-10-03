"""自评服务（v2.0.0 P4，ADR-011 §4）：纯规则计分 + urgent 开案（source=assessment）。

修 409 死环：assessment 工单的 thread_id 是 "assessment:<hex>"，**不是**图 thread。
旧 /api/review/decision 对所有工单一律走「图恢复」，自评工单查不到图状态必然 409、
永远无法闭环；v2.0.0 起裁决按台账 source 键分流（chat 源照旧图恢复，assessment 源
不碰图，见 web/routers/review.py），本层开案时写入 source="assessment" 即为其依据。

计分纯函数 score()/ITEMS/CHOICE_LABELS 保留在 cloudmaster/assessment.py 原位，
本层只复用不迁移；AssessmentError 自本模块再导出，路由从服务层导入并翻译 400。

红线：不落对话原文进台账——context_summary 是自评区间结论的固定文案，非用户输入。
"""

from __future__ import annotations

import secrets
from typing import Any

from ..assessment import AssessmentError, score

__all__ = ["AssessmentError", "submit_assessment"]


def submit_assessment(*, ledger: Any, answers: dict[str, str]) -> dict[str, Any]:
    """计分并按需开案：urgent → open_case(source="assessment") 挂到 result["escalation"]。

    AssessmentError（缺条目/选项不合法/超量程）原样向上抛，路由翻译 400；
    非 urgent 时 result["escalation"] = None（前端据 absence 展示普通转介入口）。
    thread_id 每次自评随机生成：自评可多次提交，各自独立成案、互不覆盖。
    """
    result = score(answers)
    if result["urgent"]:
        result["escalation"] = ledger.open_case(
            thread_id="assessment:" + secrets.token_hex(8),
            risk_level="high",
            basis_level="self-assessment",
            basis_reason="自评结果达「建议尽快寻求专业帮助」区间",
            context_summary="用户自评结果达到需尽快寻求专业帮助的区间",
            source="assessment",
        )
    else:
        result["escalation"] = None
    return result
