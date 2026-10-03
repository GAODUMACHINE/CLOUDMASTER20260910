# ADR-003：危机 L2 人工审核全链路（v0.3.0）

- 状态：评审通过（v0.3.0-crisis-review）
- 日期：2026-09-10
- 里程碑：v0.3.0（危机+人工审核；测试档案先行）
- 关联：指令 §4.3 human_review/工具、§6（虚构档案 A1~A7，不发真实联络）

## 上下文
v0.2.0 已完成守卫/中断恢复与持久化。v0.3.0 要求 L2 人工审核链路完整可审计，
且**测试一律用虚构档案 A1~A7，绝不触真实联络/真实热线**；L2 联络动作必须写审计
（时间/依据/审核人/结论/联络动作）。

## 决策
### 1. 新增 State 字段（本 ADR 评审，ADR-001 之外的补充）
| 字段 | 类型/reducer | 唯一写入者 | 说明 |
|---|---|---|---|
| `audit_log` | `list[dict]`，`operator.add`（只增不删） | 仅 human_review | 审核落痕：时间/依据/审核人/结论/联络动作 |
| `contact_log` | `list[dict]`，`operator.add` | 仅 human_review | 联络动作记录（桩：默认 noop 不触真实） |
| `next_followup` | `dict \| None` | 仅 human_review | L2 approve 后安排次日温和回访 |

### 2. 联络桩 ContactService
- 默认 `enabled=False`：任何联络动作只写 `action="noop-stub(不触真实联络)"` 审计，不发起真实/SMS/邮箱呼叫。
- `enabled=True` 仅在生产人工配置下启用并仍要求人审结论；测试一律用桩且断言 `noop`。
- 所有联络必须携带：contact_kind(guardian/emergency)、reviewer、decision、basis_level、时间。

### 3. L2 完整链路
crisis 判 L2 → interrupt(ADR-001 不变) → human_review 恢复读取 decision：
- approve：写审计 + 联络桩记录 + 安排次日温和回访 → 转 supervisor → empathic 交付支持。
- block：写审计（结论 block，无联络）→ 转 supervisor 交付中性/收尾。
下一轮仍必检（不跳检）。

## 后果
- 正向：L2 链路全可审计；测试不发真实联络满足红线 §6。
- 约束：审核人字段为虚构标识（如 HUMAN/A1~A7 档案），无真实个人数据；新增字段已 ADR 评审。