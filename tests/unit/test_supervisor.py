"""supervisor 路由 + 递归上限（unit）。"""

from langchain_core.messages import HumanMessage

from lightcloudmaster.supervisor import MAX_AGENT_HOPS, decide_next, supervisor_node


def _state(risk="none", hops=0, text="我最近有点累"):
    return {"messages": [HumanMessage(text)], "risk_level": risk, "agent_hops": hops, "turn_count": 0}


def test_routes_empathic_by_default():
    assert decide_next(_state()) == "empathic"


def test_knowledge_keyword_routes_knowledge():
    s = _state(text="失眠是怎么回事，能科普一下吗")
    assert decide_next(s) == "knowledge"


def test_high_risk_routes_empathic():
    s = _state(risk="high", text="科普一下")
    assert decide_next(s) == "empathic"


def test_turn_count_increments():
    out = supervisor_node(_state())
    assert out["turn_count"] == 1
    assert out["agent_hops"] == 1


def test_hops_capped_forces_end():
    s = _state(hops=MAX_AGENT_HOPS)
    out = supervisor_node(s)
    assert out["next_agent"] == "end"
