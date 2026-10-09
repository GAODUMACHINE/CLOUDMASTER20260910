"""RAG 检索可插拔契约。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Document:
    text: str
    source: str


class Retriever(Protocol):
    def retrieve(self, query: str) -> list[Document]: ...
