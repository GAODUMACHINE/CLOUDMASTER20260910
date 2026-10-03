# ADR-008：人工审核台、自评入口、隐私保留期与已审核资源（v1.2.0）

- 状态：评审通过（v1.2.0）
- 日期：2026-09-17
- 关联：ADR-001（State 契约与守卫顺序）、ADR-003（危机人工审核）、ADR-004（RAG 契约）、ADR-005（注册）、ADR-007（其「待办」由本 ADR 收口）、《办法》第 17/19/21 条、计划书 3.1.3 / 3.2.3 / 3.2.4 / 3.3.1 / 附录 A

## 上下文

对标项目计划书逐条核对后，以下**计划书已承诺但代码缺失**的能力需要补齐（保持前端 UI 风格与 Qwen 接入方式不变，改动最小化）：

1. **人工审核台**缺后端：ADR-003 只实现了「结论写回后的处理」（`crisis_chain.handle_review`），
   但「中断态 → 待审队列 → 审核员看到判定依据与上下文 → 提交结论 → 图恢复」这一条链路没有落地。
   ADR-007 已把它列为待办。
2. **情绪自评**（3.1.3-7 / 附录 A）完全缺失：计划书要求「只呈现分数区间与建议动作，不使用诊断性词汇；
   临界及以上直接给出咨询预约与热线入口」。
3. **隐私保留期与一键导出**（3.2.4 / 3.1.3-6）缺失：只有「一键删除」，没有 7/30/90 天保留期与导出。
4. **已审核热线**（TC-RES-001）缺少配置能力：红线是「不硬编码热线」，但也没有让审核台录入的入口，
   导致该功能事实上永远为空。
5. **依赖倾向识别**（3.1.3-10）只有注册时自述的静态开关，没有「高频连续使用」的自动识别。
6. 计划书附录 A.2 要求建立**合规用例集**并纳入发布门禁。

## 决策

1. **审核台作为独立台账 + 复用既有图恢复机制**，不新增图节点、不改守卫顺序：
   - 新增 `lightcloudmaster/review_queue.py`：`ReviewLedger` 以 append-only JSONL（`data/private/reviews.jsonl`，
     gitignored）记录「开案行」与「结论行」，`get()` 对已闭环工单返回 `None`，
     **保证审核结论唯一、不可覆写**；同一 thread 未闭环期间不重复开案。
   - 台账**只落判定依据与摘要，绝不落对话原文**（3.2.4「业务日志不落对话原文」硬约束）。
   - 结论写回复用 LangGraph 原生机制：`graph.update_state(cfg, {"review_decision": d})` →
     `graph.invoke(None, cfg)`，由既有 `human_review` 节点消费（`review_decision` 是 ADR-001 既有字段，
     **State 契约零变更，无需新增字段**）。
   - 接口：`GET /api/review/pending`、`GET /api/review/{ticket_id}`、`POST /api/review/decision`。
2. **审核台访问控制**：`create_app(..., reviewer_token=...)`，未配置令牌或令牌不匹配一律 **403**，
   且不区分「未开通」与「令牌错误」，避免向未授权者泄露该链路是否启用；令牌比对用
   `secrets.compare_digest`。审核台会返回会话上下文，属敏感数据，故默认最小暴露。
3. **自评实现为纯规则模块，不接入图**：新增 `lightcloudmaster/assessment.py`，4 条自拟措辞条目
   （不复制受版权保护的量表原文），计分映射为区间；返回体**不含任何分数与诊断词汇**。
   达「建议尽快寻求专业帮助」区间 → 登记审核台待审案件（与 L2 同一兜底链路，不自行处理）。
   因不写 `AgentState` 任何字段，无需 ADR-001 schema 评审。
4. **隐私保留期独立存储**：新增 `lightcloudmaster/privacy.py`，保留期偏好单独落
   `data/private/privacy.json`，**不写入画像白名单**（`profile_store.ALLOWED_FIELDS` 不放宽，
   维持最小化）；默认 30 天，仅接受 7/30/90。导出为纯函数 `export_bundle`，
   由接口把 Checkpointer 中的消息取出后组装，服务端不额外落盘原文。
5. **已审核资源库**：新增 `lightcloudmaster/resources.py`，默认返回**空列表**；
   只有经审核台录入（须令牌 + 审核人署名）的号码才下发。号码做宽松格式校验，
   允许 5 位政务服务号码，拒绝一切非号码字符（`+86`、`#`、扩展号一律拒绝）。
6. **依赖识别仍只写 `usage_meta`**：`time_guard` 新增 `detect_dependency`（近 24h 内会话
   ≥8 次即视为高频），命中也只写既有 `usage_meta`（`recent_session_starts` /
   `dependency_observed` / `disclosure_done`），**不新增顶层 State 字段**，ADR-001 不回退；
   同时仍满足「命中即短路、不消耗模型调用」。
7. **合规用例集独立成文件并纳入门禁**：新增 `tests/safety/test_compliance.py`，
   每条用例对应《办法》具体义务（TC-COMP-001~008）。
8. **测试隔离**：`tests/conftest.py` 增加 autouse fixture，把 6 个落盘存储的环境变量
   全部重定向到 `tmp_path`，确保测试**绝不写入真实 `data/private`**。

## 后果

- 正向：补齐计划书 3.1.3-6/7/10、3.2.3、3.2.4、3.3.1 与附录 A.2；审核台闭环落地，
  ADR-007 待办收口；热线上线路径（审核后录入）打通；依赖识别不再依赖用户自述。
- 约束：`reviews.jsonl` / `privacy.json` / `resources.jsonl` 与 `data/private/` 同等保护，
  均 gitignored；审核台令牌须经环境注入，不得硬编码入库。
- 待办（明确不在本次范围）：
  - 真实向量检索与知识库版本化（当前仍为 `StubRetriever` 确定性桩，ADR-004 契约不变）；
  - 长程画像（Store）与主动回访调度；
  - 审核台值班 SLA、回访话术模板的运营侧落地。