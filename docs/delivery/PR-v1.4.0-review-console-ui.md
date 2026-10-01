# PR: feat(web): v1.4.0 审核台值班界面 + 中断态语义修正（ADR-010）

> 分支：`feature/v1.1.0-online-model`（沿用当前分支）　目标：`main`（本会话授权跳过远端 push）

## 背景
上一轮补齐了审核台**后端**（ADR-008），但实测值班无法在浏览器操作，且中断态语义有三处缺陷
（回显用户原话、挂起态可被绕过、孤儿工单静默闭环）。本 PR 一并修复。

## 变更内容
### 1. 中断态：挂起占位（修「AI 回复 = 用户原话」）
- `cloudmaster/web_app.py`：新增 `REVIEW_HOLD_REPLY` 与响应字段 `held_for_review`；
  中断态下 `/api/chat` 返回安全提示占位文案，不再把 `msgs[-1]`（用户那条）当回复。
- `frontend/common/api.js`：`held_for_review` 时整段立即呈现，跳过打字机动画。

### 2. 中断态：挂起期间不推进图（修「发一条普通消息即可绕过人工审核」）
- `/api/chat` 若发现 thread 已停在 `human_review`：不再 invoke 图，改用 `graph.update_state`
  把消息追加进 state（供审核查看），返回既有工单。
- 效果：不生成自动回复、不重复登记、中断态不失效，且省掉该轮模型调用。

### 3. 孤儿工单：裁决前校验中断态（修「静默成功」）
- `POST /api/review/decision`：会话不存在 → 409；中断态失效 → 409；恢复后无 `audit_log` → 500
  且**不闭环台账**，四种情况都不再假报成功。

### 4. 审核台值班界面 `/web/review/`
- 新增 `frontend/review/{index.html,style.css,review.js}`（原生 JS，无构建、无外部依赖）。
- 待审队列 → 案件详情（判定依据 + 上下文 + 用户回信）→ 结论写回 → 结果回显；含刷新/退出。
- 安全：令牌只存 `sessionStorage`；服务端内容一律 `textContent` 渲染（防 XSS）；页面无热线号码。

### 5. 文档
- `docs/adr/ADR-010-review-console-web-and-hold.md`；`docs/run-local.md` 补值班网页入口与挂起语义。

## 测试计划
| 层 | 文件 | 覆盖 |
|---|---|---|
| integration | test_review_console.py | 挂起占位不回显、挂起期非危机消息不可绕过、孤儿工单 409 且不闭环、值班页可访问且无令牌/号码 |

## 自测摘要
- `ruff check .` ✓　`ruff format --check .` ✓（96 files）
- `pytest`：**244 passed, 2 deselected**；`pytest -m safety`：**34 passed**；`pytest -m eval`：**2 passed**
- `node --check frontend/review/review.js`、`frontend/common/api.js` ✓

## 红线核对
值班页不展示/不保存任何热线号码（测试断言无 3 位以上数字串）；页面不内置任何令牌字面量；
服务端内容全部 `textContent` 渲染，无 `innerHTML`；联络动作仍为 `noop` 桩；台账仍不含对话原文。

## 待办
1. 审核人身份仍是自填标识，多人值班需补鉴权与权限模型。
2. 挂起期间用户消息只留痕不回答——如需「审核中也可回复」，须单独评审话术与合规。
3. 本分支上仍有一批未提交改动（v1.2.0 计划书补齐 / v1.3.0 邮件），提交前需先跑全量回归。