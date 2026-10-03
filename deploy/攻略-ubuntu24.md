# CloudMaster 上线攻略：Ubuntu 24.04 + 新加坡服务器 + lightcloudmaster.top

> 面向首次部署的手把手清单。全程约 20~30 分钟（不含 DNS 生效等待）。
> 新加坡节点的三个既定事实：**免 ICP 备案**、**GitHub 直连顺畅**、**服务器时区是
> UTC**（定时任务已显式按北京时间执行，无需你做任何事）。

## 第 0 步：准备清单

| 需要 | 说明 |
|---|---|
| 服务器公网 IP | Ubuntu 24.04 镜像，最低配 1C1G 即可 |
| root 登录方式 | 密码或 SSH 密钥（云厂商控制台可重置） |
| 域名解析权限 | lightcloudmaster.top 在哪家注册的，进它的解析控制台 |
| 一个邮箱 | Let's Encrypt 证书通知用 |
| 本机终端 | Windows 自带 PowerShell 即可（内置 ssh/scp） |

## 第 1 步：DNS 解析（两条 A 记录，缺一不可）

在域名解析控制台添加 **两条** A 记录，值都是服务器公网 IP：

| 主机记录 | 记录类型 | 记录值 |
|---|---|---|
| `@` | A | `<服务器IP>` |
| `www` | A | `<服务器IP>` |

**为什么必须两条**：TLS 证书要同时覆盖 `lightcloudmaster.top` 和 `www.lightcloudmaster.top`
（nginx 配置里裸域会 301 到 www），Let's Encrypt 会逐个域名验证——只解析 www 的
话，证书签发会卡在裸域验证上失败。

等 5~10 分钟后在 PowerShell 里验证（两条都要出 IP 才算生效）：

```powershell
nslookup lightcloudmaster.top
nslookup www.lightcloudmaster.top
```

> 新加坡服务器**不需要 ICP 备案**。域名在大陆注册商处购买不影响——解析到境外
> 服务器即可直接使用。

## 第 2 步：放行端口（云控制台，不是服务器里）

在云厂商控制台的**安全组 / 防火墙**面板放行：**22**（SSH，通常默认开）、**80**、**443**。
这是新手最常卡的一步——服务器内部没问题但控制台没放行，表现为「curl 通不了、
浏览器转圈」。

服务器内部的 ufw 在 Ubuntu 24.04 云镜像上默认是 inactive，不用管。

## 第 3 步：SSH 登录服务器

```powershell
ssh root@<服务器IP>
# 有的镜像缺省用户是 ubuntu（提示 Permission denied 就换它试试）：
# ssh ubuntu@<服务器IP>   登进去后执行  sudo -i  切 root
```

## 第 4 步：拉代码 + 一键装配

```bash
# 4.1 克隆仓库（新加坡直连 GitHub，几秒）
git clone https://github.com/GAODUMACHINE/CLOUDMASTER20260910.git /opt/cloudmaster
cd /opt/cloudmaster/deploy

# 4.2 一键装配（重复执行安全；CERT_EMAIL 是证书通知邮箱，用你常用的真实邮箱）
CERT_EMAIL=你的邮箱@example.com bash bootstrap.sh
```

说明：
- `BRANCH` 参数**现在可以省略**——main 已是 v2.0.0（2026-10-03 起）。要部署**老版本
  v1.4.0**（回顾/对照用）：`BRANCH=legacy/v1.4.0 bash bootstrap.sh`（老版本冻结在
  `legacy/v1.4.0` 分支 + `v1.4.0` 标签，GitHub 页面左上角分支切换器可随时浏览）。
- 脚本会自动：装 git/nginx/certbot → 装 Python 依赖 → 生成 `.env` 骨架 → 创建
  `cloudmaster` 系统账号 → 注册 systemd 服务与每日定时任务 → 签发 TLS 证书 →
  配好 nginx。任何一步报错，**修掉原因后直接重跑同一条命令**（幂等）。

## 第 5 步：填配置（唯一的手工编辑）

```bash
nano /opt/cloudmaster/.env
```

按用途二选一：

**A. 演示模式（推荐先走通）**——不用任何密钥：

```
CM_STUB=1
CM_REVIEWER_TOKEN=<下面命令生成的随机串>
```

**B. 真实模型模式**：

```
QWEN_API_KEY=sk-你的真实key
QWEN_API_HOST=dashscope.aliyuncs.com
QWEN_MODEL=qwen-flash
CM_STUB=0
CM_REVIEWER_TOKEN=<下面命令生成的随机串>
```

生成审核台令牌（在服务器上执行，复制输出到 .env）：

```bash
openssl rand -hex 24
```

`SMTP_*` / `IMAP_*` 邮件凭据暂不填：邮件通道会**如实关闭**（报告发送返回「未配置」，
绝不假装成功），不影响其余功能。`Ctrl+O` 保存、`Ctrl+X` 退出。

## 第 6 步：启动 + 验证

```bash
systemctl enable --now cloudmaster
systemctl status cloudmaster --no-pager      # 应为 active (running)
```

三层验证，从内到外：

```bash
# 1) 应用本体（服务器内）
curl -sI http://127.0.0.1:8000/web/ | head -1          # → HTTP/1.1 200 OK

# 2) HTTPS 全链路
curl -sI https://www.lightcloudmaster.top/ | head -1   # → HTTP/2 200

# 3) 定时任务已在册
systemctl list-timers cloudmaster-jobs.timer           # 下次触发 09:17（北京时间）
```

然后浏览器（本机）打开 **https://www.lightcloudmaster.top/**，走一遍验收：

- [ ] 注册（年龄邮箱 → 协议勾选 → 进入对话页）
- [ ] 发消息，**回复逐字流出**（这是真 token SSE；若整段蹦出 → 第 8 节坑 5）
- [ ] 设置页：保留期切换、退订开关有按钮且能切换
- [ ] 资源页：申诉入口可达，默认无热线号码（正常）
- [ ] 新开标签开 `/web/review/`，粘贴 `CM_REVIEWER_TOKEN` 能看到待审队列

## 第 7 步：日常运维速查

```bash
journalctl -u cloudmaster -f                             # 实时日志
bash /opt/cloudmaster/deploy/update.sh                   # 更新（拉代码→重装→重启）
systemctl restart cloudmaster                            # 改完 .env 后重启生效
.venv/bin/python -m scripts.run_jobs                     # 手动跑一次定时任务
tar czf backup-$(date +%F).tgz -C /opt/cloudmaster data  # 冷备（含用户数据，勿外传）
```

回滚：`git -C /opt/cloudmaster checkout <旧提交>` 然后重跑 `update.sh`。

## 第 8 步：踩坑排查（按出现概率排序）

| 症状 | 原因与解法 |
|---|---|
| 浏览器打不开，curl 也超时 | 安全组没放行 80/443（第 2 步）——九成是这个 |
| bootstrap 卡在 certbot / 证书签发失败 | ① DNS 还没生效（回第 1 步验证）② 只加了一条 A 记录（必须两条）③ 安全组 80 没放行（验证要走 80）。修好后直接重跑 bootstrap |
| `certbot` 报 "Another instance" 或 80 被占 | 重跑前 `systemctl stop nginx`，签完再 `systemctl start nginx`（bootstrap 重跑会自动接续） |
| 页面能开，发消息 500 | `.env` 的 QWEN_API_KEY 没填/错；或 key 只开了 workspace 专属端点（403）→ 确认 `QWEN_API_HOST=dashscope.aliyuncs.com` 公共端点。改完 `systemctl restart cloudmaster` |
| 回复整段蹦出、不逐字流 | 浏览器缓存了旧前端：`Ctrl+F5` 强刷；仍不行看 nginx 配置里 `proxy_buffering off` 是否在位（`grep -n buffering /etc/nginx/sites-available/cloudmaster`） |
| 打开是空白/卡注册页 | 同上，旧前端缓存，`Ctrl+F5` |
| 审核台永远 403 | `.env` 没配 `CM_REVIEWER_TOKEN` 或输错——未配置与错误同文案（有意设计，不泄露链路状态）；改后重启服务 |
| systemd 服务起不来 | `journalctl -u cloudmaster -n 50` 看报错；多数是 .env 手改时格式错了（等号两边不要加空格） |
| 访问慢 | 大陆→新加坡 RTT 约 70~120ms，属正常；首字延迟主要来自模型（qwen-flash P95≈0.34s），流式观感应当流畅 |

## 上线性质提醒（三句话）

1. 代码回归全绿（243 passed / safety 34）≠ 发布门禁通过——危机语料批量召回、
   在线评估等 11 项门禁（`CLOUDMASTER20260910-TEST.md` §9.2）还没跑，**先以
   `CM_STUB=1` 演示模式上线**，页面注明演示性质。
2. 用户数据落服务器 `/opt/cloudmaster/data/private/`（SQLite），备份文件含用户
   数据，不要传到任何公开位置。
3. 若未来转正式运营：未成年人数据出境涉及《个人信息保护法》跨境条款，需重新
   评估服务器地域与合规路径。
