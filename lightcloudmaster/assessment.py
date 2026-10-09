"""自评量表——纯规则计分，不调用任何模型。

红线：结果只呈现「区间 + 建议动作」，绝不输出分数诊断或病名；条目措辞为日常
感受描述，不复制受版权保护的量表原文；达「建议尽快寻求专业帮助」区间即升级
L2 走人工审核，不自行处理。
"""

from __future__ import annotations

from typing import Any

# 选项分值（0~3）。前端只下发 value，不下发任何分值相关文案。
CHOICE_SCALE = {"none": 0, "rare": 1, "often": 2, "always": 3}
CHOICE_LABELS = {
    "none": "完全没有",
    "rare": "有几天",
    "often": "一半以上的天数",
    "always": "几乎每天",
}

# 计分区间（4 条目满量程 12）。区间名不使用诊断性词汇。
BANDS = (
    (0, 3, "平稳", "目前没有明显困扰信号，继续保持规律作息就好。"),
    (4, 7, "需要留意", "有一些困扰信号。可以试试规律作息与呼吸放松，也可以找信任的人聊聊。"),
    (8, 9, "建议寻求支持", "困扰信号较明显。建议预约学校心理中心或专业咨询，和专业人员当面聊聊。"),
    (10, 12, "建议尽快寻求专业帮助", "困扰信号较强。请尽快联系学校心理中心、专业机构或就近医院心理科。"),
)

# 自评条目（4 类通用困扰，措辞自拟，非量表原文）。
ITEMS = (
    {"id": "mood", "text": "最近两周，情绪低落、提不起兴趣"},
    {"id": "sleep", "text": "最近两周，入睡困难、睡不安稳或睡得过多"},
    {"id": "anxiety", "text": "最近两周，紧张担心、坐立不安"},
    {"id": "function", "text": "最近两周，学习或日常事务受到影响"},
)

URGENT_BAND = "建议尽快寻求专业帮助"


class AssessmentError(ValueError):
    pass


def _band_of(total: int) -> tuple[str, str]:
    for low, high, name, advice in BANDS:
        if low <= total <= high:
            return name, advice
    raise AssessmentError("计分超出量表量程")


def score(answers: dict[str, str]) -> dict[str, Any]:
    """按答案计分出区间与建议动作。answers: {item_id: choice_key}。"""
    if not isinstance(answers, dict):
        raise AssessmentError("answers 必须为对象")
    missing = [i["id"] for i in ITEMS if i["id"] not in answers]
    if missing:
        raise AssessmentError("缺少条目：" + "、".join(missing))
    total = 0
    for item in ITEMS:
        choice = answers[item["id"]]
        if choice not in CHOICE_SCALE:
            raise AssessmentError(f"条目 {item['id']} 的选项不合法：{choice}")
        total += CHOICE_SCALE[choice]
    name, advice = _band_of(total)
    urgent = name == URGENT_BAND
    result: dict[str, Any] = {
        "band": name,
        "advice": advice,
        "urgent": urgent,
        # 明确标注不构成诊断（合规：只呈现区间与行动建议）。
        "disclaimer": "自评结果不构成任何诊断，仅供参考；如需判断请咨询专业人员。",
        "entry": {"kind": "school"},  # 建议动作对应的资源入口（转介资源页）
    }
    if urgent:
        result["urgent_message"] = (
            "你填写的困扰信号较强。这不能作为诊断，但我们建议尽快联系专业人员；"
            "如果此刻有伤害自己的想法，请立即拨打当地急救电话或就近就医，并告诉可信任的人。"
        )
    return result


def risk_level_of(result: dict[str, Any]) -> str:
    """自评 → 危机分级。达「尽快寻求专业帮助」区间即 L2（走人工审核，不自行处理）。"""
    return "high" if result.get("urgent") else "none"
