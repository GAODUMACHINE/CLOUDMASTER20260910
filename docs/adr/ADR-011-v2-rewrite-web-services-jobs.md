# ADR-011：v2.0.0 重写——Web/服务分层、鉴权、SSE 与闭环语义

- 状态：评审通过（v2.0.0-rewrite，P3~P8）
- 日期：2026-10-02
- 关联：ADR-002（会话记忆）、ADR-003（L2 人工审核）、ADR-005（注册与邮箱）、ADR-007（匿名标识）、
  ADR-009（邮件链路）、ADR-010（审核台与中断态）、ADR-012（统一 SQLite 底座）
- 对应用例：TC-STREAM-001、TC-CRI-008/009、TC-ASM-005、TC-PRIV-001/002、TC-HITL-007、TC-COMP-007

## 上下文

v1.4.0 功能齐全但结构债集中：`web_app.py` 单文件 660 行、业务逻辑写在 HTTP 端点内、
存储/编排/路由三层耦死；SSE 是「整段回复伪装成流」的伪流式；`/api/chat/stream` 完全没有
挂起检查（L2 待审期间 POST 会推进图、绕过人工审核——与 ADR-010 修过的 `/api/chat` 同型缺陷）；
自评工单（`assessment:` 前缀 thread）在审核台裁决时走「图恢复」分支必然 409，永远无法闭环；
`GET /api/report/status` 把**所有用户**的发送记录返回给任一请求者（跨用户泄漏）；
保留期「到期删除」只算时间、从不执行。重写（P3~P8）按《重写执行计划》§21-23 拆六环节落地。

## 决策

### 1. Web 层拆分与薄壳策略（P3）
`lightcloudmaster/web/` 包取代单文件：`create_app`（装配）+ `deps`（AppContext/鉴权/图辅助）+
`schemas`（Pydantic 请求模型）+ `sse` + `routers/{chat,register,report,review,assessment,privacy,appeals,resources}`。
旧模块（`web_app`/`mailer`/`inbox`/`mail_store`/`privacy`/`appeals`/`resources`/`profile_store`/
`review_queue`/`crisis_chain`/`service`）改为**同名再导出薄壳**而非删除：唯一实现归新包，
既有 246 例测试的 `from lightcloudmaster.xxx import ...` 全部不破——P1 记录的
「P3 切换后由既有集成用例覆盖 DAL」以零新用例兑现（用户指令：本项目先重构，不写测试样例）。

### 2. Bearer 鉴权（P3/P5）
- 对话侧：`Authorization: Bearer <profile_key>`（匿名 ID 即凭证，ADR-007）；缺失 → 401。
  body 只剩 `{"text"}`，匿名 ID 不再出现在请求体。
- 审核侧：`Authorization: Bearer <CM_REVIEWER_TOKEN>` 取代 query `?token=`——令牌不进 URL
  （URL 会进代理/访问日志）；未配置或不匹配一律 403，不区分「未开通」与「令牌错误」。
- `POST /api/email/confirm` **删除**（处置表 #12）：该端点以 body 传入完整收件人/主题/正文、
  仅凭单一静态令牌放行，等于开放中继；前端零调用，真实流程由 `/api/report/send`（HITL + 
  绑定匿名标识的报告令牌）覆盖。连带删除其 3 个测试用例。
- `create_app(expected_token=...)` 参数保留仅为签名兼容（防调用方炸），无消费者。

### 3. SSE 真 token 流式（P3，修 TC-STREAM-001）
`web/sse.py` 用 `graph.stream(..., stream_mode="messages")` 逐 token 下发，事件协议
`data: {"type": "token"|"reply"|"held"|"done", ...}`：
- **节点白名单** `{empathic, knowledge}`——crisis 复核/语义筛查的模型输出绝不外发（判定理由
  只经审核台给值班员，不给用户）；
- **挂起检查前置**：流式端点在推进图之前先查 `_awaiting_human_review`（修 L2 绕过）；
- **stub 自然降级**：StubLLM/测试替身是 duck 类型、零 token 回调 → 零 token 即降级为单个
  `reply` 事件。无需预判模型类型，这正是选 `stream_mode="messages"` 而非回调注入的原因；
  `create_llm` 相应加 `streaming=True`（真模型 invoke 期间才有 token 回调）。

### 4. 自评工单专用闭环（P4，修 409 死环）
`review_cases.source` 列（P1 预置，CHECK IN ('chat','assessment')）进入返回契约。
`/api/review/decision` 双分支：chat 源照旧走「图恢复」（ADR-010 三重校验不变）；
**assessment 源不碰图**——自评 thread 不是图 thread，`update_state+invoke(None)` 必然扑空。
服务层 `assessment_review_effects` 直接构造与图恢复同形的 `audit_log/contact_log/next_followup`，
台账照常闭环、审计照常留痕（联络仍为 noop 桩，ADR-003 红线不变）。

### 5. 次日回访生命周期（P7，补 TC-HITL-007 数据面）
`followups` 表：`enqueue`（approve 裁决时入队，`scheduled_at`=次日）→ `due`（到期扫描）→
`mark_done`（执行器标记）。语义上 **done = 已交付审核台待办区，而非回访已完成**——回访本身是
线下人工动作，系统职责是可见性而非执行（ADR-003 温和不打扰）。`GET /api/review/pending`
响应新增 `followups` 键（`delivered_recent`），前端回访待办区渲染；不新增路由（24 路由清单封闭）。

### 6. 任务执行器边界（P7）
`jobs/purge.run_purge`（保留期到期四件套删除：thread/画像/保留期记录/报告台账 + 汇总审计）与
`jobs/followups.run_due`（到期回访交付）均为**幂等纯函数入口**，由运维手动或外部调度触发——
不引入后台线程/调度器（零新增依赖红线；uvicorn 单进程内起线程会制造测试不可控的副作用）。
申诉台账不参与 purge（运营数据有独立处理期）。

### 7. 审计种类（P4 起统一在 DAL 层记录）
`retention_changed`（改保留期）、`data_exported`（导出）、`data_deleted`（账户删除，
detail.reason=user_delete|retention_purge）、`purge_executed`（批量清除，含 key 清单与计数）。
全部经 `db.record_audit` 落 `audit_events`（append-only 触发器兜底，ADR-012）。

### 8. 「当日」本地语义用固定 UTC+8（P2 遗留待办，在此归档）
`time_guard` 的日历日按 `timezone(timedelta(hours=8))` 而非 zoneinfo：Windows 无系统 tz 数据库，
zoneinfo 需新增 `tzdata` 依赖（违反零依赖红线）；中国 1991 年后无夏令时，本系统时间戳均产生于
2026 年后，固定 +8 与 IANA 库完全等价。

## 后果
- 正向：L2 不可经流式端点绕过；自评工单可闭环；报告发送记录按本人过滤；保留期真删除；
  回访计划进程重启不丢（旧版只落图 state）；审核令牌不进 URL；危机复核输出不外发。
- 约束：薄壳再导出意味着「删旧模块」推迟到下一个大版本（import 面即兼容面）；
  SSE 事件协议从「纯文本 data: 回复」变为 JSON 事件——前端已同步（P5），curl 调试需读 JSON。
- 待办：审核人仍是自填标识（ADR-010 待办未变）；`delivered_recent` 因表无 done_at 列
  暂不做时间过滤（LIMIT 50 截断，量级上来再迁移加列）。
