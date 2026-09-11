"""危机识别（crisis 守卫）——ADR-001：仅此处可写 risk_level。

两级判定：规则词表(高召回) + LLM 复核(降误报)，两级依据均落痕到 crisis_basis。
L0->none 正常疏导；L1->low 共情+科普(下轮必检)；L2->high 中断->人工审核(interrupt)。
词表/prompt 变更必须跑 `pytest -m safety`。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from langchain_core.language_models import BaseChatModel


class CrisisLevel(StrEnum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"


# L2：强烈自杀/自伤信号（高召回，逐条命中即 L2）
L2_WORDS = [
    "自杀",
    "想死",
    "不想活",
    "活不下去",
    "结束生命",
    "轻生",
    "跳楼",
    "割腕",
    "自残",
    "上吊",
    "吃安眠药",
    "大量服药",
    "结束这一切",
    "kill myself",
    "suicide",
    "end my life",
    "don't want to live",
    "jump off",
    "cut my wrists",
    "self harm",
]
# L1：明显痛苦/危急情绪（命中即 L1）
L1_WORDS = [
    "绝望",
    "无助",
    "崩溃",
    "撑不下去",
    "坚持不下去",
    "痛苦",
    "压抑",
    "难过想哭",
    "孤独",
    "焦虑睡不着",
    "胸口堵",
    "想放弃",
    "hopeless",
    "helpless",
    "can't go on",
]


def _find_words(text: str, words: list[str]) -> list[str]:
    lower = text.lower()
    return [w for w in words if w.lower() in lower]


def rule_classify(text: str) -> tuple[CrisisLevel, list[str]]:
    """规则词表判定：返回 (级别, 命中词)。优先 L2。"""
    l2 = _find_words(text, L2_WORDS)
    if l2:
        return CrisisLevel.L2, l2
    l1 = _find_words(text, L1_WORDS)
    if l1:
        return CrisisLevel.L1, l1
    return CrisisLevel.L0, []


CONFIRM_PROMPT = (
    "你是一名危机识别复核助手。仅依据用户原话判断是否存在“自杀/自伤”的强烈即时风险。"
    "原话：{text}\n"
    "若存在明显即时自杀/自伤风险输出 DANGER；若只是痛苦情绪但无自伤意向输出 WATCH；"
    "否则输出 SAFE。只输出一个词。"
)


def llm_confirm(llm: BaseChatModel, text: str) -> str:
    """LLM 复核降误报。返回 DANGER/WATCH/SAFE。测试一律替换为 fake LLM。"""
    prompt = CONFIRM_PROMPT.format(text=text)
    resp = llm.invoke(prompt)
    content = (getattr(resp, "content", "") or "").strip().upper()
    if "DANGER" in content:
        return "DANGER"
    if "WATCH" in content:
        return "WATCH"
    return "SAFE"


def classify(text: str, llm: BaseChatModel | None = None) -> dict[str, Any]:
    """两级判定入口，返回落痕 crisis_basis。"""
    rule_level, matched = rule_classify(text)
    basis: dict[str, Any] = {"rule_level": rule_level.value, "matched_words": matched, "llm_level": None}
    base_reason = f"规则命中{len(matched)}个关键词" if matched else "无规则命中"
    final_level = rule_level
    llm_used = False

    if llm is not None and rule_level in (CrisisLevel.L1, CrisisLevel.L2):
        llm_result = llm_confirm(llm, text)
        basis["llm_level"] = llm_result
        llm_used = True
        if llm_result == "SAFE":
            final_level = CrisisLevel.L1 if rule_level == CrisisLevel.L2 else CrisisLevel.L0

    reason = base_reason + ("；LLM复核=SAFE，降级" if (llm_used and basis.get("llm_level") == "SAFE") else "")
    basis.update(
        {
            "final_level": final_level.value,
            "reason": reason,
            "confirmed_by_llm": llm_used,
        }
    )
    return basis


RISK_LEVEL_MAP = {CrisisLevel.L0: "none", CrisisLevel.L1: "low", CrisisLevel.L2: "high"}


def risk_level_of(basis: dict[str, Any]) -> str:
    level = CrisisLevel(basis["final_level"])
    return RISK_LEVEL_MAP[level]
