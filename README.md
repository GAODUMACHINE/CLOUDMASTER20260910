# LightCloudMaster 拾光云上

面向 18-25 岁青年的 AI 心理陪伴与疏导助手：支持性陪伴、心理科普与转介，
**不做诊断、治疗建议与用药信息**。服务形态为 Web（cloud-glass 前端 + FastAPI/
LangGraph 后端），Android 端为网站的最薄 WebView 封装。

## 仓库结构

```
lightcloudmaster/   后端：LangGraph 图（time_guard → crisis → supervisor）、
                    FastAPI web 层、SQLite 存储层、邮件链路、定时任务
frontend/           前端：cloud-glass（用户端）与 review（人工审核台），零构建静态页
mobile/             Android WebView 客户端（零第三方依赖，见 mobile/README.md）
deploy/             服务器部署：bootstrap.sh 一键装配、nginx 配置、运维手册
scripts/            run_jobs.py：systemd timer 调用的定时任务入口
data/private/       运行数据（gitignored，绝不入库）
```

## 本地运行

```cmd
python -m venv .venv
.venv\Scripts\pip install -e .
copy .env.example .env    :: 填 QWEN_API_KEY，或先 CM_STUB=1 走替身模型
run_web.cmd               :: http://127.0.0.1:8000/web/cloud-glass/
```

## 服务器部署

见 `deploy/README.md`（Ubuntu 22.04/24.04，nginx + uvicorn 单 worker + systemd
timer 每日回访交付与保留期清除；首次走查看 `deploy/攻略-ubuntu24.md`）。

## Android 客户端

`mobile/` 下 Gradle Wrapper 自足（需 JDK 17），构建与签名说明见 `mobile/README.md`。
App 打开即进入 `https://www.lightcloudmaster.top/`，业务全部在站点侧。

## 红线（改动前先读）

- 危机分级 L2 必须中断自动回复并转人工审核，任何端点不得绕过挂起检查；
- 台账不落对话原文；审核台不展示真实热线号码，号码仅经人工审核录入后下发；
- <14 岁数据处理一律拒绝；密钥只经 .env/环境变量注入，绝不入库。
