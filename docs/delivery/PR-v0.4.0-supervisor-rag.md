# PR: feat(rag): v0.4.0 supervisor+RAG+time_guard（ADR-004）引用必附 + 库外边界

> 分支：`feature/v0.4.0-supervisor-rag`　目标：`main`（本会话授权跳过远端 push）

## 变更内容
- ADR-004（先评审）：RAG 检索契约——可插拔 Retriever；命中必附引用(原文片段+来源)；库外不编造来源、声明边界转专业资源；来源一律虚构可溯源。
- `lightcloudmaster/rag/`：base = Retriever 协议 + Document；stub = 确定性内存语料（主题关键词子串匹配）。
- `lightcloudmaster/agents/knowledge.py`：命中→回复附「参考来源」并写 citations；库外→边界声明、citations 不新增。
- `lightcloudmaster/graph.py`：build_graph(row `retriever=None`→StubRetriever)，knowledge 节点接入。
- citations 仍仅 knowledge 写（ADR-001 不变）；守卫顺序未改。

## 测试计划
| 层 | 文件 | 覆盖 |
|---|---|---|
| unit | tests/unit/test_rag_contract.py | 库内命中 / 库外为空 |
| integration | tests/integration/test_rag.py | 命中→citations+参考来源 / 库外→边界无引用 |

## 自测摘要（make pre 全绿）
ruff ✓　format ✓　pytest：52 passed　pytest -m safety：4/4（漏检=0）

## 待办
远端配置后 `git push -u origin feature/v0.4.0-supervisor-rag` 并开 PR（squash merge）。
知识库更新走版本化+评估集回归（v1.0.0 归档）。