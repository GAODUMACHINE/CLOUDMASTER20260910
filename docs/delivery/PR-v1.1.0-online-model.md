# PR: feat(model): v1.1.0 真实模型在线接通 + 危机语义召回 + 匿名隔离与合规入口（ADR-006/007）

> 分支：`feature/v1.1.0-online-model`　目标：`main`（本会话授权跳过远端 push）

## 背景
上一轮的 key 对工作空间端点返回 `403 Model access denied`，只能以 `CM_STUB=1` 本地替身跑通流程。
本轮拿到新 key，先做连通性定位，再把真实模型接入并在线核验门禁。

## 变更内容
### 1. 真实模型接通
- `.env`：`QWEN_API_HOST=dashscope.aliyuncs.com`（公共百炼端点）、`QWEN_MODEL=qwen-flash`、`CM_STUB=0`。
  新 key 对 workspace 专属端点返回 `403 Workspace endpoint access denied`，公共端点可用。
- 模型选型实测：`qwen3.5-flash` 为思考模型，首 token ≈14s，**不满足 TC-PERF-001**；
  `qwen-flash` 首 token P50 0.26s / P95 0.33s，设为生产默认（`config.py` 默认值同步）。
- `.env.example`、`docs/run-local.md` 同步端点、模型与排障说明。

### 2. 危机识别双层判定改为「双向」（ADR-006，**待第二人复核**）
- 原实现只在规则词表命中时才调用 LLM 复核 → 附录 A 类别 2/3/4/5/6（计划安排、告别暗示、
  绝望自贬、伤害他人、变体绕过）**结构性漏检**（真实模型实测 13 条中 8 条漏检）。
- `classify()`：规则未命中时新增 `llm_screen`（SCREEN_PROMPT，按类别枚举 DANGER 条件）；
  规则命中时 `llm_confirm` 支持 DANGER 升级；`crisis_basis` 新增 `llm_mode` 落痕。
- 词表补齐附录 A 类别 7 低危对照词（想哭 / 低落 / 一无是处 / 提不起劲）。
- 在线实测：召回 **100%（21/21）**，漏检 **0**，误报 **0%**（8 条对照）。

### 3. 匿名身份隔离与合规入口（ADR-007）
- 修 **跨用户串会话**：`profile_key` 原为 `hash(age)` 推导，同龄用户共用同一 `thread_id`
  （且受 `PYTHONHASHSEED` 影响跨进程漂移）→ 改为 `secrets.token_urlsafe(12)`。
- 新增 `DELETE /api/profile/{key}`（幂等、不泄露标识是否存在）、`POST /api/appeal`（工单号）、
  `GET /api/resources`（不含任何热线号码）；`cloudmaster/appeals.py` append-only 台账。
- 前端「设置与资源」面板：转介资源、申诉表单、一键删除退出、产品边界说明；
  未成年模式标记持久化（刷新后不再丢失）。

### 4. ReAct 无工具空转修复
- 真实模型看到 `TOOL:` 协议但无工具可用时，反复调用不存在的工具、白跑满 `max_steps` 落到兜底话术。
- 无工具时改用 `NO_TOOL_PROMPT`（不宣传 TOOL 协议），未知工具观察追加「当前没有可用工具」提示。

### 5. 评估与文档
- `tests/fixtures/crisis_corpus.py`：附录 A 类别 1~8 合成语料（21 高危 + 3 低危 + 5 干扰）。
- `tests/safety/`：9 项回归（规则层漏检=0、双层结构可达、低危/干扰不得判 high、语义层不误升级）。
- `scripts/online_eval.py`：手动在线评估（首 token P95 / 危机召回误报 / 路由 / 端到端 + L2 中断核验），
  产出 `docs/eval/v1.1.0-online-report.md` 与 `.json`（**不在 CI、不是 pytest 用例**）。
- `scripts/empathy_sample.py` + `docs/eval/empathy-rubric.md`：共情评分所需的人工抽样与口径（不臆造分数）。
- ADR-006 / ADR-007；`docs/eval` 归档更新；version → 1.1.0。

## 测试计划
| 层 | 文件 | 覆盖 |
|---|---|---|
| unit | test_crisis.py | 规则分级、复核升降级、语义筛查补漏检、误报控制 |
| unit | test_react.py | 无工具 prompt 不宣传 TOOL、未知工具提示、max_steps 兜底 |
| unit | test_model_stub.py | 替身对复核/筛查 prompt 均返 SAFE |
| integration | test_web_api.py | 同龄注册 ID 唯一、thread 隔离、删除退出、申诉工单、资源页无号码 |
| safety | test_safety_crisis.py / test_safety_fixtures.py | 附录 A 语料漏检=0、双层可达、误报受控 |
| 手动在线 | scripts/online_eval.py | 首 token P95、真实模型召回/误报、路由、L2 中断 |

## 自测摘要
- `ruff check .` ✓　`ruff format --check .` ✓（74 files）
- `pytest`：**90 passed, 2 deselected**；`pytest -m safety`：**9 passed**；`pytest -m eval`：**2 passed**
- 在线（`qwen-flash`，20 样本）：首 token P50 0.27s / **P95 0.33s ✅**；危机召回 **100%（21 条）**、
  **漏检 0 ✅**、误报 **0%（8 条）✅**；路由 **100%（10 条）✅**；L2 在 human_review 前中断 ✅；
  端到端整轮 P50 1.41s / P95 2.33s（非流式，门禁口径是首 token）。
- `node --check frontend/common/api.js` ✓

## 红线核对
密钥仅存 gitignored `.env`（代码与文档零硬编码）；无真实热线号码（资源页测试断言无号码数字串）；
无真实联络/SMS/SMTP（联络桩 noop、Mailer 内存桩）；守卫顺序未改；测试零触网（server.py 与
online_eval.py 不被任何 pytest 用例导入）；`data/private/` 全部 gitignored。

## 待办（下一轮）
1. **ADR-006 涉及危机识别契约，合并前需第二人复核**（§1.4）。
2. 真实流式 SSE：`/api/chat/stream` 目前一次性返回整段（非真流式），前端用打字机模拟观感；
   需按 LangGraph `stream_mode="messages"` + 节点过滤（避免泄露危机判定 token）改造，并补 TC-CHAT-002 打断。
3. 人工审核台：TC-HITL-003（判定依据展示）、TC-HITL-004（结论写回）尚无 UI。
4. 共情评分人工标注（工具已就绪）；路由评估集扩到 ≥100 条、高危语料扩到 ≥200 条。
5. 远端配置后 `git push -u origin feature/v1.1.0-online-model` 并开 PR（squash merge）；
   注意 `origin/main` 目前落后于本地全部特性提交，合并前需对齐。