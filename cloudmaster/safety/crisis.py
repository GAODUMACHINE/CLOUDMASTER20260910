"""危机识别（crisis 守卫）——ADR-001：仅此处可写 risk_level。

两级判定：规则词表(高召回) + LLM 复核(双向：降误报 + 补漏检)，两级依据均落痕到 crisis_basis。
L0->none 正常疏导；L1->low 共情+科普(下轮必检)；L2->high 中断->人工审核(interrupt)。

LLM 层的两个方向（缺一不可，见 TC-CRI-004/005/006/007 与附录 A 类别 2~6）：
- 规则命中 L1/L2 → 复核（confirm）：SAFE 降级、DANGER 升至 L2（降误报）；
- 规则未命中   → 语义筛查（screen）：计划安排/告别暗示/绝望自贬/伤害他人/隐喻与变体绕过（补漏检）。

词表/prompt 变更必须跑 `pytest -m safety`，并跑 `scripts/online_eval.py` 在线核验召回。
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
    "想哭",
    "孤独",
    "焦虑睡不着",
    "胸口堵",
    "想放弃",
    # 注意：不要把「低落」这类过于宽泛的词放进 L1——影视观感、一时吐槽也会命中，
    # 会把干扰项误升为 low（附录 A 类别 8 要求不得判 L2，且误报要受控）。
    # 持续低落由更具体的词（一无是处/提不起劲）或 LLM 语义层承接。
    "一无是处",
    "提不起劲",
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
    "你是一名危机识别复核助手。仅依据用户原话判断是否存在“自杀/自伤/伤害他人”的强烈即时风险。"
    "原话：{text}\n"
    "若存在明显即时的自杀、自伤或伤害他人风险（含为自杀做准备、交代后事、告别暗示、隐喻表达）输出 DANGER；"
    "若只是痛苦情绪但无上述意向输出 WATCH；否则输出 SAFE。只输出一个词。"
)

# 语义筛查：规则词表未命中时的安全网（附录 A 类别 2/3/4/5/6 防漏检关键类）。
SCREEN_PROMPT = (
    "你是一名危机风险语义筛查助手。请判断用户原话是否包含自杀、自伤或伤害他人的风险信号。\n"
    "出现以下任一项即判 DANGER："
    "①直接表达自杀或自伤意图；"
    "②为自杀做准备或安排后事（交代密码、写遗书、整理或送走物品）；"
    "③告别或永别暗示（最后一次聊、帮我照顾好家人、以后就拜托你了）；"
    "④绝望自贬并带有消失或解脱意味（我是累赘、没有我大家更好、早点消失）；"
    "⑤伤害他人的意图或计划；"
    "⑥隐喻或变体表达（想去很远很远的地方、去那边、谐音、拼音缩写、多语言混排）。\n"
    "原话：{text}\n"
    "判 WATCH 的门槛要高：仅当出现明显且持续的强烈痛苦（绝望、无助、撑不下去、长期失眠、持续想哭、"
    "强烈孤独）时才输出 WATCH。"
    "若只是一时心情不好、日常吐槽或抱怨（考试没考好、和室友闹别扭、作业多、看电影有点丧）"
    "且不含上述任何信号，一律输出 SAFE。"
    "只输出一个词。"
)


def _verdict(content: str) -> str:
    """把模型输出归一为 DANGER / WATCH / SAFE。"""
    text = (content or "").strip().upper()
    if "DANGER" in text:
        return "DANGER"
    if "WATCH" in text:
        return "WATCH"
    return "SAFE"


def llm_confirm(llm: BaseChatModel, text: str) -> str:
    """LLM 复核降误报。返回 DANGER/WATCH/SAFE。测试一律替换为 fake LLM。"""
    resp = llm.invoke(CONFIRM_PROMPT.format(text=text))
    return _verdict(getattr(resp, "content", "") or "")


def llm_screen(llm: BaseChatModel, text: str) -> str:
    """LLM 语义筛查补漏检（规则未命中时调用）。返回 DANGER/WATCH/SAFE。"""
    resp = llm.invoke(SCREEN_PROMPT.format(text=text))
    return _verdict(getattr(resp, "content", "") or "")


def _reason(
    rule_level: CrisisLevel,
    matched: list[str],
    llm_level: str | None,
    llm_mode: str | None,
    final_level: CrisisLevel,
) -> str:
    parts = [f"规则命中{len(matched)}个关键词" if matched else "无规则命中"]
    if llm_mode == "confirm" and llm_level is not None:
        if llm_level == "SAFE":
            parts.append("LLM复核=SAFE，降级")
        elif llm_level == "DANGER" and rule_level != CrisisLevel.L2:
            parts.append("LLM复核=DANGER，升级")
        else:
            parts.append(f"LLM复核={llm_level}，维持")
    elif llm_mode == "screen" and llm_level is not None:
        if llm_level == "SAFE":
            parts.append("LLM语义筛查=SAFE")
        else:
            parts.append(f"LLM语义筛查={llm_level}，升级")
    if final_level == rule_level and llm_mode is None:
        parts.append("仅规则层判定")
    return "；".join(parts)


def classify(text: str, llm: BaseChatModel | None = None) -> dict[str, Any]:
    """两级判定入口，返回落痕 crisis_basis（规则层 + LLM 层双向修正）。"""
    rule_level, matched = rule_classify(text)
    basis: dict[str, Any] = {
        "rule_level": rule_level.value,
        "matched_words": matched,
        "llm_level": None,
        "llm_mode": None,
    }
    final_level = rule_level
    llm_used = False

    if llm is not None and text.strip():
        llm_used = True
        if rule_level in (CrisisLevel.L1, CrisisLevel.L2):
            verdict = llm_confirm(llm, text)
            basis["llm_mode"] = "confirm"
            if verdict == "SAFE":
                final_level = CrisisLevel.L1 if rule_level == CrisisLevel.L2 else CrisisLevel.L0
            elif verdict == "DANGER":
                final_level = CrisisLevel.L2
        else:
            verdict = llm_screen(llm, text)
            basis["llm_mode"] = "screen"
            if verdict == "DANGER":
                final_level = CrisisLevel.L2
            elif verdict == "WATCH":
                final_level = CrisisLevel.L1
        basis["llm_level"] = verdict

    basis.update(
        {
            "final_level": final_level.value,
            "reason": _reason(rule_level, matched, basis["llm_level"], basis["llm_mode"], final_level),
            "confirmed_by_llm": llm_used,
        }
    )
    return basis


RISK_LEVEL_MAP = {CrisisLevel.L0: "none", CrisisLevel.L1: "low", CrisisLevel.L2: "high"}


def risk_level_of(basis: dict[str, Any]) -> str:
    level = CrisisLevel(basis["final_level"])
    return RISK_LEVEL_MAP[level]
