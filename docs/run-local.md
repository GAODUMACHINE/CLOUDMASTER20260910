# CloudMaster 本地运行指南（视觉风格：云朵玻璃）

> 目标：本机一键启动带真实 Qwen 的 FastAPI 服务，前端使用「云朵玻璃 /web/cloud-glass/」。

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
打开 **http://127.0.0.1:8000/web/cloud-glass/**。

## 3. 能力（与后端契约一致）
- `POST /api/register`：年龄门（<14 强拒 / 未成年需监护人信号）、最小画像 + **每人唯一的随机匿名 ID**。
- `POST /api/chat`：返回 reply + risk_level + next_agent + basis_reason；L2 中断转人工审核（不自动回复）。
- `POST /api/chat/stream`：SSE 流式。
- `DELETE /api/profile/{key}`：一键删除匿名画像与会话数据（幂等，不泄露标识是否存在）。
- `POST /api/appeal`：申诉与投诉举报受理，返回工单号（落 `data/private/appeals.jsonl`）。
- `GET /api/resources`：转介资源 + 申诉入口元数据（**不含任何未审核热线号码**）。
- AI 内容标识 + 匿名隐私 + prefers-reduced-motion 全部内置。

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
