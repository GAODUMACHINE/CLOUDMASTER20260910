# ADR-004：RAG 检索契约（v0.4.0 supervisor+RAG+time_guard）

- 状态：评审通过（v0.4.0-supervisor-rag）
- 日期：2026-09-10
- 里程碑：v0.4.0
- 关联：§4.3 RAG（回复必附引用；库外问题不编造来源、声明边界并转专业资源）；citations 唯一写者=knowledge

## 决策
### 1. 检索可插拔
- `lightcloudmaster/rag/base.py` 定义 `Retriever.retrieve(query) -> list[Document]`。
- 生产：v0.4.0 不强制装 FAISS/Milvus（Python3.14 生态受限，ADR-001 已记录）；提供确定性 `StubRetriever`
  走内存语料，测试一律用它；后续可换向量后端，调用面不变。
### 2. 引用必附（citations 只增不删，仅 knowledge 写）
- 命中库内：回复必须附引用（原文片段+来源），并写 `citations`。
- 库外：不编造来源，声明知识边界并转专业/线下资源，`citations` 不新增。
### 3. 来源必须虚构可溯源
- 语料来源用虚构标识（如「青少年心理科普库 v1（虚构）」），绝不影响真实文献/机构、不发真实热线。
### 4. 知识库更新走版本化 + 评估集回归（v1.0.0 评估归档）

## 后果
- 正向：引用可溯源；库外安全边界；检索可拔插不锁死后端。
- 约束：citations 仍仅 knowledge 写（ADR-001 不变）；触网/真实检索在测试禁止。