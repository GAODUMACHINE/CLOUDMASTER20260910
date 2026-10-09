"""确定性检索桩：内存虚构语料，绝不引用真实文献/机构。"""

from __future__ import annotations

from .base import Document


class StubRetriever:
    def __init__(self, corpus: list[Document] | None = None):
        self._corpus = corpus or _CORPUS

    def retrieve(self, query: str) -> list[Document]:
        """按语料主题关键词子串匹配；库外问题返回空列表。"""
        q = query.lower()
        hits = []
        for doc in self._corpus:
            topic = doc.text.split("：")[0].lower()
            if topic and topic in q:
                hits.append(doc)
        return hits


_CORPUS = [
    Document("睡眠：睡前半小时放下电子屏幕、保持规律作息并避免咖啡因。", "青少年心理科普库 v1（虚构）"),
    Document("焦虑：尝试 4-6 秒缓慢深呼吸，把注意力放回当下。", "青少年心理科普库 v1（虚构）"),
    Document("压力：把大目标拆成小步骤，写下三个可立刻执行的动作。", "青少年心理科普库 v1（虚构）"),
]
