# ADR-007：匿名身份隔离、便捷退出与申诉入口（v1.1.0）

- 状态：评审通过（v1.1.0-online-model）
- 日期：2026-09-11
- 关联：ADR-002（会话记忆）、ADR-005（注册）、《CLOUDMASTER20260910-TEST.md》TC-REG-006 / TC-PRIV-004 / TC-PRIV-006 / TC-RES-002、《办法》第 19、21 条

## 上下文
1. v0.5.0 的 `/api/register` 用 `"anon-" + str(abs(hash(str(age))))` 生成 `profile_key`。
   该值**只由年龄决定**，而 `profile_key` 同时是 Checkpointer 的 `thread_id`——两个同龄用户会读到
   同一段会话历史，构成用户数据越权/串会话；同时 CPython 的 `hash(str)` 受 `PYTHONHASHSEED` 影响，
   进程重启后同一用户的 ID 会漂移，历史会话无法接续。
2. 合规用例 TC-PRIV-004（便捷退出/删除，第 19 条）与 TC-PRIV-006 / TC-RES-002（申诉与投诉举报入口，第 21 条）
   在后端与前端均缺失。

## 决策
1. `profile_key = "anon-" + secrets.token_urlsafe(12)`：每人唯一、不可预测、跨进程稳定。
2. `DELETE /api/profile/{profile_key}`：删除最小画像 + `checkpointer.delete_thread(thread_id)`；
   **幂等**，且对未知标识同样返回成功——避免用状态码枚举「某匿名标识是否已注册」。
3. `POST /api/appeal`（kind / text / profile_key）：受理申诉与投诉举报，追加写入
   `data/private/appeals.jsonl`（append-only、gitignored），返回可追踪工单号 `AP-xxxxxx`；
   仅收最小字段，不索取姓名或联系方式（隐私最小化）。
4. `GET /api/resources`：转介资源清单 + 申诉入口元数据；**不下发任何未审核热线号码**
   （红线：热线须经人工审核后由审核台配置）。
5. 前端新增「设置与资源」面板：资源清单、申诉表单、一键删除退出、产品边界说明；
   未成年模式标记随会话持久化到 localStorage，刷新后不再丢失。

## 后果
- 正向：消除跨用户串会话与跨进程 ID 漂移；补齐《办法》第 19/21 条对应的产品入口。
- 约束：申诉台账含用户主动提交的文本，须与 `data/private/` 同等保护并按保留期清理（TC-SEC-001/002）。
- 待办：审核台（TC-HITL-003 判定依据展示、TC-HITL-004 结论写回）仍待实现，不在本次范围。