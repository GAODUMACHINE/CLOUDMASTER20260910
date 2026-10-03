# CloudMaster 部署指南（lightcloudmaster.top）

> **手把手走查（首次部署看这篇）：[攻略-ubuntu24.md](攻略-ubuntu24.md)**——
> 按实际环境（Ubuntu 24.04 / 新加坡节点 / 大陆访问）写的线性清单，含踩坑排查表。
> 本文件是参考手册；目标：把本仓库部署到一台 Linux 服务器，以
> `https://www.lightcloudmaster.top` 对外提供服务。
> 组件：nginx（TLS + SSE 反代）→ uvicorn（127.0.0.1:8000）→ SQLite（data/private/）。
> 全部资产在 `deploy/`：`bootstrap.sh`（一键装配）、`update.sh`（例行更新）、
> `nginx-cloudmaster.conf`（站点配置）。

## 0. 上线前必读（合规红线，先于一切技术步骤）

本系统处理**自杀危机识别与未成年人数据**。公网上线 ≠ 代码能跑即可：

- 《人工智能拟人化互动服务管理暂行办法》第 22/23 条要求**上线前安全评估并报告**；
  本仓库的对应物是 `CLOUDMASTER20260910-TEST.md` §9.2 发布门禁检查表（11 项，
  含高危语料召回 ≥95%、HITL 全链路演练、安全评估材料归档）。**代码回归全绿
  （243 passed / safety 34，2026-10-02）不等于门禁通过**。
- 建议路线：先以 **`CM_STUB=1` 演示模式**上线（替身模型，零额度不触网，功能完整），
  页面注明演示性质；门禁全绿后再切真实模型。
- 域名解析到**中国大陆**服务器须先完成 **ICP 备案**（约 1~2 周）；解析到香港/海外
  节点免备案但大陆访问延迟略高。备案期间可先用服务器裸 IP + HTTPS 联调。
- 审核台（`/web/review/`）有独立令牌门禁，但它是敏感链路——正式运行时建议再加
  网络层限制（如仅值班 IP 可访问该路径）。

## 1. 前提

| 项 | 要求 |
|---|---|
| 服务器 | Ubuntu 22.04 / 24.04，1C1G 起步即可（SQLite 单机、单 worker） |
| DNS | `lightcloudmaster.top` 与 `www` 两条 A 记录 → 服务器公网 IP |
| 端口 | 安全组/防火墙放行 80、443 |
| 邮箱 | 一个用于 Let's Encrypt 通知的邮箱 |

## 2. 一键装配

```bash
# SSH 到服务器（root）
CERT_EMAIL=you@example.com bash bootstrap.sh
```

脚本幂等，重跑安全。它会：装依赖 → 克隆代码（缺省 `main` = v2.0.0；
`BRANCH=legacy/v1.4.0` 可部署冻结的老版本）→ 建 venv 并安装 → 生成 `.env` 骨架 →
建 `cloudmaster` 系统账号 → 写 systemd 服务与**每日定时器**（北京时间 09:17 回访交付 +
保留期清除）→ 签发 TLS 证书（webroot，自动续期挂钩）→ 安装 nginx 站点配置。

## 3. 装配后必做的两步

```bash
# 1) 填密钥（只存在服务器本机，绝不入库）
vim /opt/cloudmaster/.env
#   必填：QWEN_API_KEY（真实模型）或临时 CM_STUB=1（替身演示）
#   必填：CM_REVIEWER_TOKEN（审核台；留空则审核台一律 403——默认最小暴露）
#   选填：SMTP_*/IMAP_*（不填则邮件通道如实关闭，报告发送会返回「未配置」）

# 2) 启动
systemctl enable --now cloudmaster
systemctl status cloudmaster --no-pager
```

验证：

```bash
curl -I https://www.lightcloudmaster.top/        # 301→HTTPS、200
curl -I https://www.lightcloudmaster.top/web/cloud-glass/   # 200
```

浏览器走一遍注册 → 对话 → 设置页；值班端 `https://www.lightcloudmaster.top/web/review/`。

## 4. 日常运维

| 动作 | 命令 |
|---|---|
| 看日志 | `journalctl -u cloudmaster -f` |
| 例行更新 | `bash /opt/cloudmaster/deploy/update.sh`（git pull → 重装 → 重启） |
| 回滚 | `git -C /opt/cloudmaster checkout <旧提交>` 后重跑 `update.sh` |
| 定时任务 | `systemctl list-timers cloudmaster-jobs.timer`；手动跑：`.venv/bin/python -m scripts.run_jobs`（输出单行 JSON，purge 失败退出码 2） |
| 备份 | `sqlite3 /opt/cloudmaster/data/private/*.db ".backup ..."` 或直接整目录冷备（停服后拷贝）；**备份文件含用户数据，绝不入 git / 不发外部** |
| 续期 | certbot 自动；手动测试 `certbot renew --dry-run` |

## 5. 架构约束（为什么是这些配置）

- **单 worker**：存储层为每库单连接 + 进程内锁（ADR-012），横向加 worker 前须先做
  存储并发设计——不要 `--workers N`。
- **SSE**：nginx 站点配置里 `proxy_buffering off` 不可删——删了 token 被攒成整段，
  真 SSE 退化回伪流式（v2.0.0 P3 的核心修复作废）。
- **只读仓库**：systemd `ProtectSystem=strict` 下仓库只读、仅 `data/` 可写；
  部署时 `compileall` 预编译字节码。更新后重跑 update.sh 即重新预编译。
- **数据边界**：用户数据只落 `data/private/`（gitignored）；`.env` 为 `640 root:cloudmaster`
  （systemd 以 root 读 EnvironmentFile、服务进程以组身份读 pydantic-settings，其他用户不可见）。
  仓库本身可公开（已验证无敏感文件入库）。
