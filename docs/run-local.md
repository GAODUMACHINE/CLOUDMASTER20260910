# CloudMaster 本地运行指南（视觉风格：云朵玻璃）

> 目标：本机一键启动带真实 Qwen 的 FastAPI 服务，前端使用「云朵玻璃 /web/cloud-glass/」。

## 1. 配置（密钥不入库）
- 复制 `.env.example` 为 `.env`（已存在则直接编辑）。
- `.env` 在 `.gitignore` 中（`git check-ignore .env` 应返回规则），**绝不提交**。真实密钥只存在于本机 `.env`。
- 已按你的接入信息填入：
  | 变量 | 值 |
  |---|---|
  | QWEN_API_KEY | sk-bf...(你提供的真实 key) |
  | QWEN_API_HOST | ws-9jjokj7wljatienj.cn-beijing.maas.aliyuncs.com |
  | QWEN_MODEL | qwen3.5-flash |
  base_url 自动推断为 `https://<host>/compatible-mode/v1`（OpenAI 兼容）。

## 2. 启动
```powershell
# PowerShell（Windows）
.\run_web.ps1
# 或直接
& .\.venv\Scripts\python.exe -m uvicorn cloudmaster.server:app --host 127.0.0.1 --port 8000
```
打开 **http://127.0.0.1:8000/web/cloud-glass/**。

## 3. 能力（与后端契约一致）
- POST /api/register：年龄门（<14 强拒 / 未成年需监护人信号）、最小画像匿名 ID。
- POST /api/chat：返回 reply + risk_level + next_agent；L2 走人工审核（邮件桩 Mailer，未确认不发送；不放真实热线）。
- POST /api/chat/stream：SSE 流式。
- AI 内容标识 + 匿名隐私 + prefers-reduced-motion 全部内置。

## 4. 测试 / 安全回归（禁止触网）
- 测试一律注入 fake LLM：`.\venv` 下 `pytest`（默认跳过 eval）、`pytest -m safety`、`pytest -m eval`。
- `make pre` = ruff check + format --check + pytest。
- 本机真实模型只出现在 `server.py`（生产），**不被任何测试导入**。

## 5. 安全红线核对
- 密钥仅存 `.env`（gitignored）；代码零硬编码。
- 不索取真名/照片/联系方式；<14 严禁；危机升级人工审核；不提供未审核热线；动效 reduce-motion 支持。
- 涉及危机识别/用户数据的合流需 2 人 approve。