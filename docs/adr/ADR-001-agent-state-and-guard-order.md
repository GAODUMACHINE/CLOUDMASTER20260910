# ADR-001：AgentState 与守卫顺序（图拓扑契约）

- 状态：**已评审通过（v0.1.0-core）**
- 日期：2026-09-10
- 里程碑：v0.1.0（单 Agent ReAct 底座）
- 关联：LIGHTCLOUDMASTER 干活指令 §4.3（State 写入权限表）、§4.4（测试分层）、§8（v0.1.0）

## 上下文

本产品为 18-25 岁青年 AI 心理陪伴与疏导助手。红线要求：任何对外可用版本必须自带完整兜底链路，
守卫顺序 `time_guard → crisis → supervisor/子 Agent` 不得绕过；`risk_level`/`next_agent`/`usage_meta`
等字段有**唯一写入者**；新增/修改 State 字段必须先 ADR 评审，获批才动代码。

本 ADR 固化 v0.1.0 的 AgentState 全字段 schema、reducer、唯一写入者，以及图拓扑与危机分级映射。

## 决策

### 1. 守卫顺序（不可绕过）

```
START → time_guard → crisis → supervisor → empathic/knowledge
                              ↑                    |
                              └──── 子 Agent 完毕 ──┘（多跳，受上限保护）
crisis 判 L2 时：在 human_review 前 interrupt_before 中断（StaticInterrupt），
                人工审核结论写回 State 后图从 human_review 恢复
```

### 2. AgentState（TypedDict，langgraph）

| 字段 | 类型 | reducer | 唯一写入者 | 说明 |
|---|---|---|---|---|
| `messages` | `list[BaseMessage]` | `add_messages` | 各对话节点 | 对话消息流 |
| `risk_level` | `str` | 覆盖赋值 | 仅 crisis | `none/low/high`，L0→none、L1→low、L2→high |
| `next_agent` | `str` | 覆盖赋值 | 仅 supervisor | `empathic/knowledge/end` |
| `citations` | `list[dict]` | `operator.add`（只增不删） | 仅 knowledge | 引用：原文片段+来源 |
| `turn_count` | `int` | 覆盖赋值 | 仅 supervisor | 会话轮次，每轮自增 |
| `user_profile` | `dict` | 覆盖赋值 | 服务层注入，图内只读 | 默认最小化画像 |
| `usage_meta` | `dict` | 覆盖赋值 | 仅 time_guard | 时长/收尾状态，供 Checkpointer 持久化 |
| `crisis_basis` | `dict` | 覆盖赋值 | 仅 crisis | 判定依据落痕（命中词/级别/理由），供审计与人工审核台 |
| `agent_hops` | `int` | 覆盖赋值 | 仅 supervisor | 多 agent 跳数计数；超过上限强制 `next_agent=end` + 告警（防死循环） |
| `review_decision` | `str` | 覆盖赋值 | 仅 human_review | `pending/approve/block`，L2 人工审核结论 |

注：`agent_hops`/`review_decision`/`crisis_basis` 为本 ADR 依据 §4.3 表外新增字段，故需评审；图内递归上限
由 `agent_hops` 实现，满足红线 §6-7（条件边防死循环：上限 + trace 告警）。

### 3. 危机分级映射

| L 级 | risk_level | 行为 |
|---|---|---|
| L0 | `none` | 正常疏导 |
| L1 | `low` | 共情强化 + 心理科普 + 下轮必检 |
| L2 | `high` | 中断自动回复 → 热线卡片 → human_review 人工审核 → 必要时联络监护人/紧急联系人 → 全量审计 → 次日温和回访 |

L0/L1 后下一轮仍必检（不跳检）；词表/prompt 变更必须跑 `pytest -m safety`。

### 4. 模型层

- 生产模型：Qwen3.5-Flash（OpenAI 兼容），通过 `.env`（gitignored）注入 `QWEN_API_KEY/HOST/MODEL`；
  代码不得硬编码密钥或绝对路径。
- 测试一律用 `langchain_core.language_models.fake_chat_models` 替换，**禁止调用真实模型 API**。

## 后果

- 正向：字段写入权单一，越权可被测试或评审发现；危机两判定落痕可审计；防死循环具备图内上限。
- 约束：任何后续对 State 字段的增改必须先 ADR；测试不得触网；L2 依赖 human_review 恢复链路完整。
- 风险：Python 3.14 生态较新，FAISS 等后续里程碑安装可能受限；不影响本 ADR 范围（v0.1.0 无需向量库）。