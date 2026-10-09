"""单 Agent ReAct：text 风格决策协议——输出以 `TOOL:` 开头则调用工具并进入下一轮，
否则视为最终答案。受 max_steps 上限保护（防死循环），超出用兜底回复。
prompt 禁区：不诊断/不开药/不评判。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from .prompts import (
    NO_TOOL_MINOR_PROMPT,
    NO_TOOL_PROMPT,
    REACT_PROMPT,
)

__all__ = [
    "react_agent",
    "MAX_STEPS",
    "REACT_PROMPT",
    "NO_TOOL_PROMPT",
    "NO_TOOL_MINOR_PROMPT",
    "FALLBACK_ANSWER",
]

logger = logging.getLogger(__name__)

MAX_STEPS = 4

FALLBACK_ANSWER = (
    "我在这里陪着你。如果情绪持续加重或出现伤害自己的念头，请及时联系可信任的人，或使用审核台提供的紧急资源。"
)
UNKNOWN_TOOL = "工具不存在"
NO_TOOL_HINT = "（当前没有可用工具，请直接给出最终支持性回复，不要再用 TOOL:）"
TOOL_ERROR = "工具执行异常：{exc}"


def _next_text(llm: Any, prompt: str) -> str:
    reply = llm.invoke(prompt)
    return str(getattr(reply, "content", "") or "").strip()


def react_agent(
    llm: Any,
    text: str,
    tools: dict[str, Callable[[str], str]] | None = None,
    max_steps: int = MAX_STEPS,
    *,
    minor_mode: bool = False,
) -> str:
    """单 Agent ReAct 主循环，返回最终回复文案。

    `tools` 为空（empathic 节点的情形）时改用 NO_TOOL_PROMPT：不再宣传 TOOL 协议，
    避免真实模型反复调用不存在的工具、白跑满 max_steps 才落到兜底话术。
    `minor_mode=True`（未成年用户）时用收紧模板。
    """
    tools = tools or {}
    if tools:
        base = REACT_PROMPT
    elif minor_mode:
        base = NO_TOOL_MINOR_PROMPT
    else:
        base = NO_TOOL_PROMPT
    prompt = base.format(text=text)
    answer: str | None = None
    for _ in range(max_steps):
        decision = _next_text(llm, prompt)
        if decision.startswith("TOOL:"):
            name, _, arg = decision[len("TOOL:") :].partition(":")
            name = name.strip()
            fn = tools.get(name)
            if fn is None:
                observation = UNKNOWN_TOOL + (NO_TOOL_HINT if not tools else "")
            else:
                try:
                    observation = fn(arg.strip())
                except Exception as exc:  # noqa: BLE001 -- 工具容错，单次异常不打断整个会话
                    observation = TOOL_ERROR.format(exc=exc)
            logger.warning("ReAct 收到 TOOL 调用但无匹配工具 name=%r，已回注观察继续", name)
            prompt = prompt + f"\n观察：{observation}"
            continue
        answer = decision
        break
    if answer is None:
        logger.warning("ReAct 达到 max_steps=%s 仍未直接作答，回退兜底回复", max_steps)
        return FALLBACK_ANSWER
    return answer
