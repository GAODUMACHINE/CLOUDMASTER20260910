"""单 Agent ReAct（v0.1.0 功能承载）。text 风格决策协议：输出以 `TOOL:` 开头则调用工具并进入下一轮，
否则视为最终答案。受 max_steps 上限保护（防死循环，ADR-001 递归上限），超出用兜底回复。
prompt 禁区：不诊断/不开药/不评判。测试一律注入 fake LLM，禁止触网。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

MAX_STEPS = 4

REACT_PROMPT = (
    "你是一名面向18-25岁青年的心理陪伴助手（ReAct）。若需工具则输出一行 `TOOL:<工具名>:<参数>`，"
    "否则直接给出最终支持性回复。绝不给出诊断结论、不开药、不评判。用户的话：{text}"
)
# 无工具可用时（empathic 节点即此情形）不得再宣传 TOOL 协议：真实模型会反复尝试调用不存在的工具，
# 白跑 max_steps 轮后落到兜底话术（2026-09-11 qwen-flash 在线核验发现）。
NO_TOOL_PROMPT = (
    "你是一名面向18-25岁青年的心理陪伴助手。当前没有任何可用工具，请直接给出最终支持性回复，"
    "不要输出以 `TOOL:` 开头的内容。绝不给出诊断结论、不开药、不评判。用户的话：{text}"
)
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
) -> str:
    """单 Agent ReAct 主循环，返回最终回复文案。

    `tools` 为空（empathic 节点的情形）时改用 NO_TOOL_PROMPT：不再宣传 TOOL 协议，
    避免真实模型反复调用不存在的工具、白跑满 max_steps 才落到兜底话术。
    """
    tools = tools or {}
    prompt = (REACT_PROMPT if tools else NO_TOOL_PROMPT).format(text=text)
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
                except Exception as exc:  # noqa: BLE001  -- 工具容错，避免单次异常打断整个会话
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
