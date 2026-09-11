"""图组装——守卫顺序 time_guard → crisis → supervisor → empathic/knowledge（ADR-001，不可绕过）。
L2 时在 human_review 前 interrupt_before 中断；人工审核结论写回后图恢复。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from langgraph.graph import END, START, StateGraph

from .safety.crisis import classify, risk_level_of
from .state import AgentState
from .supervisor import supervisor_node

_AGENTS = {}


def _last_user_text(state: dict[str, Any]) -> str:
    for m in reversed(state.get("messages") or []):
        if getattr(m, "type", "") == "human":
            return str(m.content)
    return ""


def _time_guard(state: dict[str, Any], now_fn: Callable[[], datetime] | None) -> dict[str, Any]:
    from .time_guard import time_guard_node

    return time_guard_node(state, now=now_fn() if now_fn else None)


def _crisis(state: dict[str, Any], llm: Any) -> dict[str, Any]:
    basis = classify(_last_user_text(state), llm)
    return {"risk_level": risk_level_of(basis), "crisis_basis": basis}


def _human_review(state: dict[str, Any]) -> dict[str, Any]:
    from langchain_core.messages import AIMessage

    from .crisis_chain import handle_review

    decision = state.get("review_decision") or "pending"
    note = "（L2 危机）人工审核结论：" + decision
    update: dict[str, Any] = {"review_decision": decision, "messages": [AIMessage(note)]}
    if decision in ("approve", "block"):
        update.update(handle_review(state.get("crisis_basis") or {}, decision))
    return update


def _after_time_guard(state: dict[str, Any]) -> str:
    usage = state.get("usage_meta") or {}
    return "end" if usage.get("fired") else "crisis"


def _after_crisis(state: dict[str, Any]) -> str:
    return "human_review" if state.get("risk_level") == "high" else "supervisor"


def _after_supervisor(state: dict[str, Any]) -> str:
    return state.get("next_agent", "end")


def build_graph(llm: Any, now_fn: Callable[[], datetime] | None = None, checkpointer: Any = None):
    """构造 LangGraph。llm 在测试中必须为 fake ChatModel，勿传生产模型于测试。"""

    def tg(s: dict[str, Any]) -> dict[str, Any]:
        return _time_guard(s, now_fn)

    g = StateGraph(AgentState)
    g.add_node("time_guard", tg)
    g.add_node("crisis", lambda s: _crisis(s, llm))
    g.add_node("human_review", _human_review)
    g.add_node("supervisor", supervisor_node)
    g.add_node("empathic", _make_empathic(llm))
    g.add_node("knowledge", _make_knowledge(llm))

    g.add_edge(START, "time_guard")
    g.add_conditional_edges("time_guard", _after_time_guard, {"end": END, "crisis": "crisis"})
    g.add_conditional_edges(
        "crisis", _after_crisis, {"human_review": "human_review", "supervisor": "supervisor"}
    )
    g.add_edge("human_review", "supervisor")
    g.add_conditional_edges(
        "supervisor", _after_supervisor, {"empathic": "empathic", "knowledge": "knowledge", "end": END}
    )
    g.add_edge("empathic", END)
    g.add_edge("knowledge", END)

    if checkpointer is None:
        from langgraph.checkpoint.memory import InMemorySaver

        checkpointer = InMemorySaver()
    return g.compile(checkpointer=checkpointer, interrupt_before=["human_review"])


def _make_empathic(llm: Any):
    from .agents.empathic import empathic_node

    return lambda s: empathic_node(s, llm)


def _make_knowledge(llm: Any):
    from .agents.knowledge import knowledge_node

    return lambda s: knowledge_node(s, llm)
