# CloudMaster 本地运行指南（视觉风格：云朵玻璃）

> 目标：本机一键启动带真实 Qwen 的 FastAPI 服务，前端使用「云朵玻璃 /web/cloud-glass/」。
> **公网部署（lightcloudmaster.top）见 [deploy/README.md](../deploy/README.md)**——
> nginx + systemd + TLS + 每日定时任务一键装配；本文只覆盖本机运行。

## 1. 配置（密钥不入库）
- 复制 `.env.example` 为 `.env`（已存在则直接编辑）。
- `.env` 在 `.gitignore` 中（`git check-ignore .env` 应返回规则），**绝不提交**。真实密钥只存在于本机 `.env`。
- 当前接入信息：

  | 变量 | 值 | 说明 |
  |---|---|---|
  | QWEN_API_KEY | `<本机 .env 中的真实 key>` | 真实密钥，仅在本机，不入库 |
  | QWEN_API_HOST | `dashscope.aliyuncs.com` | 百炼公共端点 |
  | QWEN_MODEL | `qwen-flash` | 生产模型，首 token P50≈0.3s |
  | CM_STUB | `0` | 关闭本地替身，走真实模型 |

  `base_url` 自动推断为 `https://<host>/compatible-mode/v1`（OpenAI 兼容），亦可用 `QWEN_BASE_URL` 覆盖。

- **模型选型注意**：`qwen3.5-flash` 是思考模型，实测首 token ≈14s，不满足 TC-PERF-001（≤2s）；
  `qwen-flash` 实测首 token P50≈0.26s / P95≈0.34s，为生产默认。
- **端点注意**：workspace 专属端点（`ws-<id>.cn-beijing.maas.aliyuncs.com`）对部分 key 返回
  `403 Workspace endpoint access denied`；公共端点 `dashscope.aliyuncs.com` 可用。两者都用同一套
  OpenAI 兼容路径，切换只改 `QWEN_API_HOST`。
- `CM_STUB=1` 时改用本地确定性替身（`StubLLM`，零额度/不触网），仅用于模型未开通前跑通全流程。

## 2. 启动
```powershell
# PowerShell（Windows）
.\run_web.ps1
# 或直接
& .\.venv\Scripts\python.exe -m uvicorn cloudmaster.server:app --host 127.0.0.1 --port 8000
```
打开 **http://127.0.0.1:8000/web/cloud-glass/**（用户前端）。

- 也可直接打开 **http://127.0.0.1:8000/**：根路径会 307 跳转到上述页面；`/web/` 是落地页。
  （v1.4.0 修：此前 `/` 与 `/web/` 都是 404，只有一字不差输入完整路径才能进入，容易被误判成"进不去"。）
- 值班端：**http://127.0.0.1:8000/web/review/**，需先在 `.env` 配 `CM_REVIEWER_TOKEN` 并重启。
- 若浏览器打开是空白或卡在注册页（红字提示"请填写邮箱：疏导报告需要投递地址"／"请填写正确的邮箱"），
  多为**旧版前端资源缓存**：按 `Ctrl+F5` 强制刷新。v1.3.0 起重写了 HTML/CSS/JS，且注册新增了邮箱字段，
  旧缓存 JS 提交的载荷不带 `email`，后端会 400。

## 3. 能力（与后端契约一致）
> v2.0.0 起对话侧鉴权改 **Bearer 头**：`POST /api/chat` 与 `/api/chat/stream` 请求头
> `Authorization: Bearer <匿名ID>`（缺失 401「缺少 Bearer 凭证（匿名 ID）」，body 只需 `{"text"}`）。
> 其余用户侧端点（privacy/report/assessment/profile 等）仍走路径中的匿名 ID，契约不变。

- `POST /api/register`：年龄门（<14 强拒 / 未成年需监护人信号）、最小画像 + **每人唯一的随机匿名 ID**；
  v2.0.0 起协议签署同步留痕（agreements 表：版本 + 匿名键 + 时间，append-only）。
- `POST /api/chat`：返回 reply + risk_level + next_agent + basis_reason + notices；L2 中断转人工审核
  （不自动回复），并返回 `escalation.ticket_id`（受理编号，前端危机横幅展示）。
- `POST /api/chat/stream`：**真 token SSE**（事件协议见 3.5）；挂起检查与 /api/chat 同源单点实现。
- `DELETE /api/profile/{key}`：一键删除匿名画像与会话数据（幂等，不泄露标识是否存在）；同时清除保留期偏好。
- `POST /api/appeal`：申诉与投诉举报受理，返回工单号（落 SQLite `appeals` 表，同事务写 received 事件）。
- `GET /api/resources`：转介资源 + 申诉入口元数据 + `hotlines`（**默认空数组，不含任何未审核热线号码**）。

### 3.1 情绪自评（v1.2.0，非诊断）
- `GET /api/assessment/items`：4 条日常感受条目 + 4 档选项 + 免责声明。
- `POST /api/assessment` body `{"answers":{"mood":"none|rare|often|always", ...}}`：
  只返回**区间 + 建议动作 + 免责声明**，**不含任何分数**；达「建议尽快寻求专业帮助」区间时
  自动登记人工审核待审案件（不自行处理）。

### 3.2 隐私保留期与导出（v1.2.0）
- `GET /api/privacy/{key}`：当前保留期（默认 30 天）+ 可选值 `[7,30,90]` + 到期删除时间。
- `POST /api/privacy/{key}/retention` body `{"days":7|30|90}`：仅接受这三个值，其余返回 400；
  变更写入 `audit_events`（kind=retention_changed）。导出/删除同样留审计（data_exported / data_deleted）。
- `GET /api/privacy/{key}/export`：导出本人的最小画像与会话记录（只含匿名数据，无姓名/联系方式）。
- 保留期偏好落统一 SQLite 库（见 §3.6），到期由 `jobs/purge.run_purge` 真删除（见 §3.7）。

### 3.3 人工审核台（v1.2.0，内部高危链路）
审核台会返回会话上下文，属敏感数据，**默认不开放**：须在环境变量中配置令牌后启用。

```powershell
# 启动前设置审核台令牌（示例值，请自行更换；令牌不入库）
$env:CM_REVIEWER_TOKEN = "<自定义审核台令牌>"
```

| 接口 | 说明 |
|---|---|
| `GET /api/review/pending` | 待审队列（只有判定依据与摘要，无对话原文）+ **回访待办 `followups`** |
| `GET /api/review/{ticket_id}` | 单个案件 + 上下文（用于人工判断，不落盘） |
| `POST /api/review/decision` | 写回结论：`{"ticket_id","decision":"approve\|block","reviewer","contact_kind"}` |

- **鉴权（v2.0.0）**：三个端点一律请求头 `Authorization: Bearer <CM_REVIEWER_TOKEN>`
  （`secrets.compare_digest` 常数时间比对；令牌不进 URL / 访问日志）。
  未配置令牌或令牌不匹配一律 **403**（不区分「未开通」与「令牌错误」，避免泄露链路是否启用）。
- `decision=approve` → 审计留痕 + 联络动作（`contact_kind`：`guardian`/`emergency`/`school`/`none`）+ 次日温和回访；
  `decision=block` → 仅审计留痕、不发起联络。
- 裁决分两支：**chat 工单**审核结论写回后**图自动恢复**（`update_state` → `invoke(None)`）；
  **assessment 工单**（`source=assessment`）不经过图，服务层直接构造同形审计/联络/回访——
  修掉了旧版自评 urgent 工单裁决必 409 的死环。
- 回访计划落 `followups` 队列（pending → done=已交付待办区；回访触达本身是线下人工动作），
  值班页「回访待办」区渲染近 7 日已交付项（匿名键只显前 8 字符）。
- 台账落 SQLite `review_cases` 表（append-only 语义 + 决策不可覆写约束），**绝不落对话原文**。
- **值班网页（v1.4.0）**：<http://127.0.0.1:8000/web/review/> —— 令牌在页面内输入，只存 `sessionStorage`
  （不进 URL / 不进 localStorage）；待审队列 → 判定依据 + 上下文 → approve/block + 联络对象 → 结果回显。
  服务端未配 `CM_REVIEWER_TOKEN` 时页面一律拒绝访问。
- **挂起语义（v1.4.0，ADR-010）**：L2 中断期间 `/api/chat` 返回安全提示**占位文案**并带 `held_for_review=true`，
  不生成自动回复；此间用户新消息只追加进上下文供审核查看，**不推进图**，因此工单不会被绕过、也不会失效。
- **裁决前校验中断态**：会话已删除 → 409；中断态已失效 → 409；恢复后无审计 → 500 且台账保持未闭环
  （禁止「静默成功」把工单闭环却什么都没恢复）。

### 3.4 邮件收发（v1.3.0，ADR-009）

分**系统侧账号**（发信/收信凭据，走 `.env`）与**用户侧注册邮箱**（报告投递地址）两部分。
**未配置时通道关闭且如实报错，绝不假装发送成功。**

```powershell
# 发信（SMTP）——以 QQ 邮箱为例；Outlook 用 smtp-mail.outlook.com:587 + starttls
$env:SMTP_HOST="smtp.qq.com"; $env:SMTP_PORT="465"; $env:SMTP_SECURITY="ssl"
$env:SMTP_USER="<系统发信邮箱>"; $env:SMTP_PASSWORD="<SMTP 授权码，非登录密码>"
# 收信（IMAP）——用于接收回信 / 退信 / STOP 退订
$env:IMAP_HOST="imap.qq.com"; $env:IMAP_PORT="993"
$env:IMAP_USER="<系统收件邮箱>"; $env:IMAP_PASSWORD="<IMAP 授权码>"
```

| 接口 | 说明 |
|---|---|
| `GET /api/report/{key}` | 生成报告**草稿**（不发送，落库），返回 `confirm_token` |
| `POST /api/report/send` | 前端二次确认后发送：`{"report_id","confirm_token","decision":"approve"}` |
| `GET /api/report/status/{key}` | 投递邮箱、通道是否就绪、已发送记录（**v2.0.0 起只返回本人的**） |
| `POST /api/report/unsubscribe/{key}` | 退订报告（`report_opt_in=False`）；`/resubscribe` 重新开启 |
| `POST /api/inbox/poll` | 拉取新来信（回信/退信/退订）并入库；须审核台 Bearer 令牌 |
| `GET /api/inbox` | 来信台账（只读摘要）；同上鉴权 |

- **发送是产品级 HITL**：报告只含会话**聚合信息与建议，不含对话原文**；用户先看预览、再点确认才发送。
- 确认令牌绑定「匿名标识 + 报告编号」，服务端用 `compare_digest` 比对；同一报告**不可重复投递**（409）。
- 草稿/发送台账自 v2.0.0 起落 SQLite（`report_drafts`/`report_sents`，进程重启不丢；
  `POST /api/email/confirm` 已删除——旧开放中继隐患）。
- 收信只读 `text/plain` 并**跳过附件**，正文截断 2000 字后落 SQLite `inbox_messages` 表。
- 来信分类：`reply`（主题含 `[RP-xxxx]`/`[HR-xxxx]` 即归属到报告/工单）、`bounce`（退信）、`auto`（自动回复）、`other`。
- 邮件正文含 `STOP`/`退订` 等 → 自动把对应用户的 `report_opt_in` 置 False（按发件地址回查匿名标识）。
- AI 内容标识 + 匿名隐私 + prefers-reduced-motion 全部内置。

### 3.5 SSE 流式事件协议（v2.0.0，真 token 流）

`POST /api/chat/stream`（Bearer 同 /api/chat）按序发四类事件（`data: {"type": ...}\n\n`）：

| type | 含义 |
|---|---|
| `token` | 模型增量 token（仅共情/科普节点在白名单内；危机复核材料**绝不外发**） |
| `reply` | 整段回复（非流式降级时只发这一条） |
| `held` | L2 挂起：安全提示占位文案 + ticket_id，无动画 |
| `done` | 终态：`risk_level` + `basis_reason` + `notices`（时长守护气泡） |

挂起检查**前置**（流式开始前判定），L2 无法经 stream 端点绕过人工审核。

### 3.6 数据落盘（v2.0.0 统一 SQLite 底座，ADR-012）

业务台账不再散落 JSONL，统一进 SQLite（WAL；缺省 `data/private/business.db`，gitignored）：
profiles / privacy / review_cases / appeals(+appeal_events) / resources / agreements /
report_drafts+report_sents / inbox_messages / followups / audit_events（append-only 触发器兜底）。

路径收口链（`storage/db.resolve_db_path`）：显式参数 → 各店专属环境变量 → `BUSINESS_DB_PATH`
→ `data/private/business.db`。专属变量按店命名：`PROFILE_DB_PATH` / `PRIVACY_DB_PATH` /
`REVIEW_DB_PATH` / `APPEAL_DB_PATH` / `RESOURCE_DB_PATH` / `AGREEMENT_DB_PATH` /
`REPORT_DB_PATH` / `INBOX_DB_PATH` / `FOLLOWUP_DB_PATH`（一般无需设置）。
旧 JSON 生产数据迁移走 `scripts/migrate_json_to_sqlite.py`（dry-run 对账 + 幂等）。

### 3.7 定时任务（v2.0.0 jobs/，外部调度触发，零新增依赖）

系统**不内置**调度线程；`jobs/` 提供幂等纯函数入口（`run_purge` / `run_due`），由运维
cron / Windows 计划任务装配依赖后调用。示例（与 server.py 同款装配链）：

```powershell
# 次日回访到期交付（pending → done，进审核台待办区）
& .\.venv\Scripts\python.exe -c "from cloudmaster.storage.followups import FollowupQueue; from cloudmaster.jobs.followups import run_due; print(run_due(queue=FollowupQueue()))"

# 保留期到期真删除（thread + 画像 + 保留期记录 + 报告台账；申诉台账不参与）
& .\.venv\Scripts\python.exe -c "import os; from cloudmaster.model import create_llm, create_stub_llm; from cloudmaster.graph import build_graph; from cloudmaster.persistence import build_checkpointer; from cloudmaster.profile_store import ProfileStore; from cloudmaster.privacy import PrivacyStore; from cloudmaster.storage.reports import ReportRegistry; from cloudmaster.jobs.purge import run_purge; llm = create_stub_llm() if os.environ.get('CM_STUB') == '1' else create_llm(); print(run_purge(graph=build_graph(llm, checkpointer=build_checkpointer()), profiles=ProfileStore(), privacy=PrivacyStore(), reports=ReportRegistry()))"
```

两者重复执行无副作用；清除轮次经 `privacy.log_purge` 落一条 `purge_executed` 汇总审计。

## 4. 测试 / 安全回归（禁止触网）
- 测试一律注入 fake LLM：`.\.venv\Scripts\python.exe -m pytest`（默认跳过 eval）、`pytest -m safety`、`pytest -m eval`。
- `make pre` = ruff check + format --check + pytest。
- 本机真实模型只出现在 `server.py` 与 `scripts/online_eval.py`（手动在线评估），**不被任何 pytest 用例导入**。

## 5. 在线评估（真实模型，手动）
```powershell
& .\.venv\Scripts\python.exe -m scripts.online_eval --n 20 `
    --out docs\eval\v1.1.0-online-report.md --json docs\eval\v1.1.0-online-metrics.json
```
产出首 token 延迟 P95、危机双层判定召回/误报、路由正确率、端到端延迟与 L2 中断核验。

## 6. 安全红线核对
- 密钥仅存 `.env`（gitignored）；代码零硬编码。
- 不索取真名/照片/联系方式；<14 严禁；危机升级人工审核；不提供未审核热线；动效 reduce-motion 支持。
- 涉及危机识别/用户数据的合流需 2 人 approve（ADR-006 待第二人复核）。

## 7. 启动失败？多半是执行策略拦截 .ps1
- 报错「无法加载，因为在此系统上禁止运行脚本」→ 是 PowerShell 执行策略挡住 `.ps1`。
- 解法：
  1) 双击 `run_web.cmd`（已内置 `-ExecutionPolicy Bypass`）。
  2) 或命令行一次性绕过：
     powershell -NoProfile -ExecutionPolicy Bypass -File .\run_web.ps1
  3) 或本用户放行一次：Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
- 也可完全绕过脚本，直接跑：& .\.venv\Scripts\python.exe -m uvicorn cloudmaster.server:app --host 127.0.0.1 --port 8000

## 8. 测试报 PermissionError（tmp_path 不可写）
受限沙箱/只读盘下 pytest 的 `tmp_path` 可能落在不可写目录，表现为
`PermissionError: [WinError 5] ...\Temp\pytest-of-<user>`。把临时目录指到工作区内即可：
```powershell
$env:TEMP = "$PWD\data\private\pytest-tmp"; $env:TMP = $env:TEMP
& .\.venv\Scripts\python.exe -m pytest -q
```
