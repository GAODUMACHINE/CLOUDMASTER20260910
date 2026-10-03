"""knowledge 节点——心理科普（v0.4.0 RAG，ADR-004）。仅此处可写 citations。
命中库内：必附引用(原文片段+来源)；库外：不编造来源，声明边界转专业资源。

v2.0.0 P2 真增强：检索文档**进入 prompt**（旧版只把用户问题交给模型、正文自由生成、
引用事后拼接，正文与引用可完全脱节，违背 ADR-004「回复必附引用」的实质意图）。
现在模型只能依据检索到的参考资料作答，引用列表仍是逐字原文（不变）。
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

from ..prompts import KNOWLEDGE_PROMPT  # 再导出：模板本体归 prompts.py

__all__ = ["knowledge_node", "KNOWLEDGE_PROMPT", "OUT_OF_BOUNDARY"]

OUT_OF_BOUNDARY = (
    "（该问题超出我的心理科普知识边界，我不做诊断。如需深入了解，建议线下咨询专业心理服务人员。）"
)


def _last_user_text(state: dict[str, Any]) -> str:
    for m in reversed(state.get("messages") or []):
        if getattr(m, "type", "") == "human":
            return str(m.content)
    return ""


def _to_citation(doc: Any) -> dict[str, Any]:
    return {"text": doc.text, "source": doc.source}


def knowledge_node(state: dict[str, Any], llm: Any, retriever: Any) -> dict[str, Any]:
    text = _last_user_text(state)
    docs = retriever.retrieve(text)
    if not docs:
        return {"messages": [AIMessage(OUT_OF_BOUNDARY)]}
    docs_block = "\n".join(f"- {d.text}（来源：{d.source}）" for d in docs)
    reply = llm.invoke(KNOWLEDGE_PROMPT.format(text=text, docs=docs_block))
    content = str(getattr(reply, "content", ""))
    citations = [_to_citation(d) for d in docs]
    content = content + "\n\n参考来源：\n" + "\n".join(f"- [{c['source']}]：{c['text']}" for c in citations)
    return {"messages": [AIMessage(content)], "citations": citations}
