# PR: feat(crisis): v0.3.0 危机 L2 人工审核全链路（ADR-003）+ 虚构档案 A1~A7

> 分支：`feature/v0.3.0-crisis-review`　目标：`main`（本会话授权跳过远端 push，待配置后开 PR）

## 变更内容
- ADR-003（先评审）：新增 State 字段 audit_log/contact_log/next_followup（human_review 唯一写）。
- `lightcloudmaster/crisis_chain.py`：L2 审核处理——审计落痕（时间/依据/审核人/结论/联络动作）+ 联络桩不触真实 + 次日温和回访安排。
- `human_review` 节点增强：approve→审计+联络桩+回访；block→仅审计，无联络。
- 虚构档案 A1~A7（tests/fixtures/crisis_profiles.py），绝不影响真实联络/热线（红线 §6）。
- ADR-001 守卫顺序未改；ADR-003 字段已评审。

## 测试计划
| 层 | 文件 | 覆盖 |
|---|---|---|
| unit | tests/unit/test_crisis_chain.py | 联络桩 noop、审计完整、approve/block、enabled 仅人工请求 |
| integration | tests/integration/test_crisis_review.py | L2 approve 全链路 / block 无联络 |
| safety | tests/safety/test_safety_fixtures.py | 档案 A1~A7 分级零漏检 |

## 自测摘要（make pre 全绿）
ruff check ✓  format ✓　pytest：48 passed　pytest -m safety：4/4（高危召回=1.0，漏检=0）

## 红线核对
- 无真实联络/热线（ContactService 默认 noop 桩，测试断言）；enabled 仅标记「生产人工执行」仍不自动发。
- fake LLM 全程；守卫顺序未改；本地 git；密钥/库文件未入库。

## 待办
远端配置后 `git push -u origin feature/v0.3.0-crisis-review` 并开 PR（squash merge）；涉及危机识别需 2 人 approve。