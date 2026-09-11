# PR：feat(agent): v0.1.0 单 Agent ReAct + 安全守卫骨架（ADR-001）+ 三层测试

> 分支：`feature/v0.1.0-core`　目标：`main`（待配置远端后 Push 并开 PR，squash merge）

## 变更内容
- LangGraph 图拓扑（不可绕过）：`time_guard → crisis → supervisor → empathic/knowledge`（ADR-001）。
- **单 Agent ReAct**（`cloudmaster/react.py`）：text 协议决策（`TOOL:` 行触发工具/否则即最终答案），
  `max_steps` 上限保护防死循环（红线 §6-7），超出回退兜底回复；prompt 禁区：不诊断/不开药/不评判。
- `empathic` 节点改用 ReAct 承载 L0/L1 支持性回复；L2 走 `HIGH_RISK_SUPPORT` 并由 `human_review` 人工审核。
- `time_guard`（纯规则，零模型）：未成年人 50/60 分钟、全员 120 分钟、依赖倾向 AI 生成提示；当日已收尾不重复、次日恢复；命中即短路。
- `crisis` 两级判定（L0/L1/L2，`crisis_basis` 双判定落痕）；L2→`high`→图在 `human_review` 前 `interrupt_before` 中断，人工结论写回后恢复。
- `supervisor` 唯一写 `next_agent/turn_count/agent_hops`；递归上限防死循环。
- 模型后端：Qwen3.5-Flash（OpenAI 兼容），密钥/主机经 `.env` 注入（`cloudmaster/config.py`、`cloudmaster/model.py`），**零硬编码密钥/绝对路径**。
- Checkpointer：`InMemorySaver` 按 thread 持久化（L2 中断恢复依赖）。
- ADR-001 先评审后编码；State 字段写入权契约见 `docs/adr/ADR-001-agent-state-and-guard-order.md`。

## 测试计划
| 层 | 文件 | 覆盖 |
|---|---|---|
| unit | tests/unit/{test_crisis,test_time_guard,test_supervisor,test_react}.py | 判定/阈值/路由/递归上限/ReAct 直答与工具序列与兜底 |
| integration | tests/integration/test_graph.py | 完整图：守卫顺序 + L0 到达 empathic + knowledge 路由 + L2 中断→恢复 |
| safety | tests/safety/test_safety_crisis.py | 高危语料全捕获，漏检=0 一票否决；误报≤10% |

## 自测结果摘要（`make pre` 全绿）
- `ruff check .`：通过（0 error）。
- `ruff format --check .`：通过。
- `pytest -q`：**30 passed**（0 失败，0.29s）。
- `pytest -m safety -q`：**3/3 通过**（高危召回=1.0，漏检=0）。

## TC 覆盖说明
- 未成年时长/收尾、依赖倾向 AI 提示 → 对应 `TC-TG-*`（time_guard）。
- 危机每轮必检、L2 中断→人工恢复 → `TC-CRI-009` / `TC-HITL-001` 语义。
- 高危漏检=0 → §6 一票否决门禁（`pytest -m safety`）。

## 合规与红线核对
- 全程本地 git 配置（无 `--global/--system`）；`user.email=gaodumachine@outlook.com` 未改动。
- `.env` 未入库（已 gitignore）；无密钥/数据库/日志/大文件入库。
- 测试全部 fake LLM（`GenericFakeChatModel`），零触网/零真实模型调用。
- 守卫顺序未被绕过；State 字段变更已 ADR 评审。

## 待办
- **待配置远端**：未提供 remote URL → 按 §2.4 跳过 push；提供后执行 `git push -u origin feature/v0.1.0-core` 并开 PR（squash merge）。
- 涉及**危机识别**，按 §4.5 需 **2 人 approve** 方可合并。