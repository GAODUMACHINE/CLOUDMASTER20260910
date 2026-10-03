# PR: feat(plan-gap): v1.2.0 补齐计划书缺口——人工审核台 / 自评 / 隐私保留期 / 已审核资源（ADR-008）

> 分支：`feature/v1.1.0-online-model`（本地，**未推送**）　目标：`main`
> 约束：前端 UI 风格与 Qwen 接入方式保持不变，整体文件改动最小化。

## 背景

以《拾光云上——基于 Multi-Agent 协作模式的青年心理疏导系统》项目计划书逐条核对代码，
确认以下**计划书已承诺但尚未实现**的能力，本轮补齐：

| 计划书出处 | 缺失能力 | 状态 |
| --- | --- | --- |
| 3.2.3 / 3.3.1（ADR-007 待办） | 人工审核台：待审队列 → 判定依据与上下文 → 结论写回 → 闭环 | 本轮实现 |
| 3.1.3-7 / 附录 A | 情绪自评：只呈现区间与建议动作，临界及以上转介 | 本轮实现 |
| 3.2.4 / 3.1.3-6 | 会话保留期 7/30/90 天可配 + 一键导出 | 本轮实现 |
| TC-RES-001 | 已审核热线的录入能力（此前无入口，功能事实上永远为空） | 本轮实现 |
| 3.1.3-10 | 依赖倾向识别（此前只有注册时自述的静态开关） | 本轮实现 |
| 附录 A.2 | 合规用例集并纳入发布门禁 | 本轮实现 |

## 变更内容

### 1. 人工审核台（`lightcloudmaster/review_queue.py` + 3 个接口）
- `ReviewLedger`：append-only JSONL（`data/private/reviews.jsonl`，gitignored）。
  **开案行 + 结论行**两段式；`get()` 对已闭环工单返回 `None`，保证结论唯一不可覆写；
  同一 thread 未闭环期间不重复开案；闭环后再次触发可重新开案。
- 台账**只落判定依据与摘要（`basis_reason` ≤500、`context_summary` ≤200），绝不落对话原文**
  （3.2.4「业务日志不落对话原文」硬约束），并有单测锁定该约束。
- 接口：`GET /api/review/pending`、`GET /api/review/{ticket_id}`、`POST /api/review/decision`。
- **结论写重复用 LangGraph 原生机制**：`graph.update_state(cfg, {"review_decision": d})` →
  `graph.invoke(None, cfg)`，由既有 `human_review` 节点消费。`review_decision` 是 ADR-001 既有字段，
  **State 契约零变更、图结构与守卫顺序零变更**。
- 访问控制：`create_app(..., reviewer_token=...)`；未配置令牌或令牌不匹配一律 **403**，
  且不区分「未开通」与「令牌错误」以免泄露链路是否启用；比对用 `secrets.compare_digest`。
- `/api/chat` 在 `risk_level=high` 时返回 `escalation.ticket_id`，前端危机横幅显示受理编号。

### 2. 情绪自评（`lightcloudmaster/assessment.py`）
- 4 条**自拟措辞**的日常感受条目（不复制任何受版权保护的量表原文），4 档选项，
  计分映射为 4 个区间（平稳 / 需要留意 / 建议寻求支持 / 建议尽快寻求专业帮助）。
- 返回体**不含任何分数**，只用区间名 + 建议动作 + 「不构成诊断」声明；前端亦不渲染分数。
- 达「建议尽快寻求专业帮助」区间 → 登记审核台待审案件（**不自行处理**，与 L2 同一兜底链路）。
- 实现为**纯规则模块、不接入图**，不写 `AgentState` 任何字段，故 ADR-001 无需 schema 变更。

### 3. 隐私保留期与一键导出（`lightcloudmaster/privacy.py`）
- 保留期偏好独立落 `data/private/privacy.json`，**不写入画像白名单**
  （`profile_store.ALLOWED_FIELDS` 不放宽，隐私最小化不变）；默认 30 天，仅接受 7/30/90。
- `purge_schedule` 给出 `created_at + retention_days` 的到期删除时间与是否已过期。
- `export_bundle` 为纯函数：最小画像 + 会话消息 + 保留期；原文只回传本人，服务端不额外落盘。
- 接口：`GET /api/privacy/{key}`、`POST /api/privacy/{key}/retention`、`GET /api/privacy/{key}/export`；
  删除账号时同步清除保留期偏好。

### 4. 已审核资源（`lightcloudmaster/resources.py`）
- 默认返回**空列表**；只有经审核台录入（**须令牌 + 审核人署名，缺一不可**）才下发。
- 号码宽松格式校验：允许 5 位政务服务号码（如 12345），拒绝 `+86`、`#`、扩展号等一切非号码字符。
- 前端在既有 `<ul id="resourceList">` 中追加已审核条目，号码用 `<span class="hotline-tel">` 呈现；
  空数组不渲染任何内容（安全默认）。

### 5. 依赖倾向自动识别（`lightcloudmaster/time_guard.py`）
- 新增 `detect_dependency`：近 24h 内会话次数 ≥8 次即判为高频连续使用。
- 命中（自述 **或** 自动识别）→ 提示并写 `usage_meta.recent_session_starts` /
  `dependency_observed` / `disclosure_done`——**均为既有 `usage_meta` 字段，不新增顶层 State 字段**。
- 仍满足「命中即短路、不消耗模型调用」；越窗旧记录自动淘汰。

### 6. 前端（保持云朵玻璃 v1.3 视觉体系，最小改动）
- `index.html`：设置面板新增「情绪自评（非诊断）」区与「会话保留期 / 导出」控件。
- `style.css`：按既有 token 新增自评与热线样式（`--paper`/`--hairline`/`--accent`/`--r-md`），
  未引入任何新色板；不含任何硬编码号码。
- `common/api.js`：新增 `setupAssessment()` / `setupPrivacy()` / `setupHotlines()`；
  `/api/resources` 改为**单次共享请求**（原设置面板与热线条目不再重复拉取）；
  危机横幅在已知工单号时显示受理编号。保持纯 ES5（无箭头函数/模板字符串）。

### 7. 测试与文档
- `tests/conftest.py`：新增 autouse fixture，把 6 个落盘存储的环境变量重定向到 `tmp_path`，
  确保测试**绝不写入真实 `data/private`**。
- 新增用例：`test_assessment.py`(10)、`test_review_queue.py`(8)、`test_privacy.py`(8)、
  `test_resources.py`(7)、`test_review_console.py`(18 集成)、`test_compliance.py`(22 合规)、
  `test_time_guard.py` 扩充 6 条依赖识别用例。
- `docs/adr/ADR-008-review-console-assessment-privacy.md`：记录本轮决策与明确的不做项。

## 验证结果（全部 exit 0）

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| Lint | `ruff check .` / `ruff format --check .` | All checks passed / 87 files already formatted |
| 单测+集成+安全 | `pytest` | **173 passed**, 2 deselected |
| 安全回归（含合规用例集） | `pytest -m safety` | **31 passed**（原 9 + 合规 22） |
| 评估集 | `pytest -m eval` | 2 passed |
| 前端语法 | `node --check frontend/common/api.js` | exit 0 |
| 端到端（`CM_STUB=1`，不触网） | TestClient 真实 app | 见下 |

端到端实测（真实 app + StubLLM）：静态页 200 且新容器就位；注册 → 聊天回复正常、
`escalation=None`（非高危不开案）；自评 4 条目 → 区间「建议寻求支持」且**返回体无 score 字段**；
保留期默认 30 → 改 90 且给出 `delete_after`；导出含 2 条消息、画像仅 `{age,is_minor}`；
`/api/resources` 的 `hotlines` 为**空数组**、entries 4 条。

## 明确不在本次范围（ADR-008 待办）

- 真实向量检索与知识库版本化：仍为 `StubRetriever` 确定性桩（ADR-004 契约不变）；
- 长程画像（Store）与主动回访调度、监护人查询使用概况页；
- 审核台值班 SLA、回访话术模板的运营侧落地；
- 三步式注册与监护人/紧急联系人**联系方式**采集——按隐私最小化红线，仍只保留
  `guardian_contact_available` / `emergency_contact_available` **布尔信号**，不采集号码本身。