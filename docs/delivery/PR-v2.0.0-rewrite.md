# PR: feat(v2.0.0): 全量重写——Web/服务分层 + SQLite 底座切换 + 前端契约闭环（ADR-011/012）

> 分支：`feature/v2.0.0-rewrite`　目标：`main`（squash-merge 策略；中间提交不保证独立可导入）
> 前置：P0 基线（27c74bb）→ P1 存储层（b89cdda）→ P2 图修复（4d1756a），均已单独提交。
> 本 PR：P3~P8 六环节一口气落地（用户指令：先重构、不写测试样例、不跑测试）。
>
> **合并记录（2026-10-03）**：main 以 **no-ff 合并提交**收编本分支——分叉原因是仓库
> 初始提交（94e8eca）仅含 LICENSE 且只在 main 线上，合并把 LICENSE 补入本线；全部
> 过程提交历史保留，未 squash（回归转绿与审计修复的过程提交有存档价值）。v1.4.0 老版本
> 冻结于 `legacy/v1.4.0` 分支（726aa3c，老线最终态）+ `v1.4.0` 标签（b069b97，发布锚点），
> 新老两版自此独立可回顾。

## 背景

v1.4.0 功能齐全但结构债集中（详见 ADR-011「上下文」）：`web_app.py` 单文件 660 行三层耦死；
SSE 是伪流式且 stream 端点无挂起检查（L2 可被绕过）；自评工单裁决 409 死环；
`/api/report/status` 跨用户泄漏；保留期「到期假删除」；回访计划只落图 state 重启即丢；
`/api/email/confirm` 是开放中继隐患。v2.0.0 按《重写执行计划》六环节（P3~P8）收口。

## 变更内容（六环节六提交）

### P3 feat(web)：Web 层拆分 + Bearer 鉴权 + 真 SSE
- `lightcloudmaster/web/` 包取代单文件：`__init__`（装配）/ `deps`（AppContext + 鉴权 + 图辅助 +
  挂起检查单点化）/ `schemas` / `sse` / `routers/{chat,register,report,review,assessment,privacy,appeals,resources}`。
- 鉴权新契约：chat 侧 `Authorization: Bearer <profile_key>`（匿名 ID 即凭证，缺失 401，
  body 只剩 `{"text"}`）；审核侧 `Authorization: Bearer <CM_REVIEWER_TOKEN>` 取代 query
  `?token=`（令牌不进 URL/访问日志；未配置与错误同文案 403）。
- **`POST /api/email/confirm` 删除**（处置表 #12：body 传完整收件人/主题/正文 + 单一静态令牌
  = 开放中继；前端零调用；真实流程由 `/api/report/send` 的 HITL + 一次一密报告令牌覆盖）。
  连带删除 3 个测试用例。
- 真 token SSE：`graph.stream(..., stream_mode="messages")`，事件协议
  `{"type":"token"|"reply"|"held"|"done"}`；节点白名单 `{empathic, knowledge}`（crisis 复核
  输出绝不外发）；**挂起检查前置**（修 L2 经 stream 端点绕过）；StubLLM 零 token 自动降级
  单 reply 事件；`create_llm` 加 `streaming=True`。路由表核对：22 条 /api 路由 =
  处置表 23 − email/confirm，完全对齐。
- 旧模块薄壳化：`privacy/profile_store/review_queue/resources/appeals` → storage 再导出
  （与 S2/S1/S3 负责的 mailer/inbox/mail_store/service/crisis_chain 同策略）。
- 测试契约同步（4 文件机械修改）：chat 调用 Bearer 化、审核令牌 query→header、删 3 用例。

### P4 feat(services)：业务服务层 + 存储增强 + 处置闭环
- `lightcloudmaster/services/`：`session`（service_turn 迁入）、`registration`（注册三步写 +
  **协议签署留痕**）、`assessment`（自评计分 + source=assessment 开案）、`report`
  （报告全链路 + ReportServiceError；`report_status` **按本人过滤**修跨用户泄漏）；
  `service.py` 薄壳。
- storage 增强：`reviews.open_case(source=)` + source 进返回契约；`reports.sent_records(profile_key)`
  / `delete_for_profile`；`privacy` 审计四件（retention_changed / data_exported /
  purge_executed / data_deleted via profiles.delete(reason=)）+ `all_keys`；
  `appeals` 处置闭环（APPEAL_ACTIONS / add_event / events / list_open，submit 同事务落
  received 事件）；新建 `agreements.AgreementStore`（AGREEMENT_VERSION=v2.0.0）。

### P5 feat(web)：前端契约闭环
- `api.js`：chat/stream Bearer 化；`fetch + getReader + TextDecoder` 消费 SSE 四事件
  （token 逐段追加 / reply 整段 / held 横幅无动画 / done 终态 + notices 气泡）；
  降级链（零事件→旧 POST /api/chat 打字机；中途断流保留已到内容不重发——防同句重复入账；
  401 不降级直接提示）。
- 退订开关落地（修「文案承诺随时可退订但无按钮」缺口）：`reportOptBtn`/`reportOptMsg`，
  初值自 `GET /api/report/status/{key}`，点击走 unsubscribe/resubscribe。
- `review.js`：令牌改 Authorization 头；回访待办区渲染 `followups`（匿名键只显前 8 字符）。
- 新建 `common/tokens.css` 公共设计令牌，两页统一配色（review 页向云朵玻璃体系对齐）。

### P6 feat(mail)：邮件链路服务化
- `services/mail/{smtp,parse,imap,ingest}`：自根模块逐字迁移；**compare_digest 修复**
  （send_if_confirmed 令牌比对改常数时间）；ingest 编排自 web 端点抽离；
  `mailer/inbox/mail_store` 薄壳。

### P7 feat(jobs)：危机链 + 回访队列 + 定时执行器
- `services/crisis_chain`：迁入 + `enqueue_followup`（回访落库）+ `assessment_review_effects`
  （自评工单裁决等效副作用——**修 409 死环**：assessment thread 非图 thread，裁决不再走
  图恢复，服务层直接构造同形 audit_log/contact_log/next_followup）；`crisis_chain.py` 薄壳。
- `storage/followups.FollowupQueue`：pending→done 生命周期，done=已交付待办区（回访本身
  是线下人工动作，系统只保证可见性）；`GET /api/review/pending` 新增 `followups` 键。
- `jobs/purge.run_purge`：**保留期真删除**四件套（thread/画像/保留期记录/报告台账 + 汇总
  审计；申诉台账不参与）；`jobs/followups.run_due`：到期交付。均为幂等纯函数入口，
  外部调度触发，零新增依赖。

### P8 docs(governance)：文档治理
- ADR-011（重写决策：分层/薄壳/Bearer/SSE/assessment 闭环/回访生命周期/jobs 边界/审计
  种类/固定 UTC+8 归档）、ADR-012（统一 SQLite 底座，P1 追记）。
- PR-v2.0.0（本文）、`LIGHTCLOUDMASTER20260910-TEST.md` 差距回写（附录 C）、功能对照表状态列
  收口、`docs/run-local.md` 同步新契约、`pyproject.toml` version 2.0.0。

## 自测摘要
- `ruff check .` ✓　`ruff format --check .` ✓（142 files）
- 全模块导入冒烟 ✓（薄壳→storage 同一性断言、graph 链、jobs、services.mail）
- OpenAPI 路由表核对 ✓（22 条 /api 路由与处置表逐条对齐）
- 前端红线静态扫描 ✓（审核台页面无 3 位以上数字串/令牌字面量；热线模式串全前端零命中）
- **全量回归已补跑（2026-10-02，用户解除不测试指令后）**：默认集 **243 passed + 2 deselected**、
  safety **34 passed**——与预期数一致。首跑抓出 1 个真 bug 并已修复：`ProfileStore.put`
  的 `_typed_values` 值序与 INSERT 列清单错位，email/report_opt_in 两列绑反
  （`get()` 走 data_json 无症状，STOP 退订的 email 列回查静默失效）——详见
  storage/profiles.py::_typed_values 的防回归注释。

## 红线核对
台账/报告/审计不含对话原文；未审核热线一律不下发（默认空数组）；<14 拒服务；
未配置邮件通道如实报错绝不假装成功；audit_events append-only（触发器兜底）；
审核令牌/匿名 ID 不进 URL 与日志；SSE 白名单外 chunk（crisis 判定材料）绝不外发；
联络动作仍为 noop 桩。

## 待办
1. ~~合并前补跑全量回归~~ **已完成（2026-10-02）**：243 passed + 2 deselected / safety 34，
   全绿；首跑抓出并修复 profiles 列绑定错位 1 例（见自测摘要）。
2. 审核人仍是自填标识（ADR-010 待办未变）。
3. followups 表无 done_at 列，delivered_recent 暂不做时间过滤（LIMIT 50 截断）。
4. 旧 JSON→SQLite 生产数据迁移须经 `scripts/migrate_json_to_sqlite.py`（P1 已冒烟验证）。
