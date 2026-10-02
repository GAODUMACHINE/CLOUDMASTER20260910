#!/usr/bin/env bash
# CloudMaster 服务器一键装配（Ubuntu 22.04 / 24.04，root 执行）：
#   依赖 → 仓库 → venv → .env 骨架 → systemd 服务与定时器 → TLS 证书 → nginx。
#
# 用法（在服务器上，先配好 DNS A 记录把两个域名指到本机公网 IP）：
#   CERT_EMAIL=you@example.com bash bootstrap.sh
# 可用环境变量覆盖缺省：
#   APP_DIR=/opt/cloudmaster  REPO_URL=...  BRANCH=main  DOMAIN=lightcloudmaster.top
#
# 幂等：重复执行安全（已存在的证书/.env/用户不重建）。脚本结束后需要手工做的一步
# 只有编辑 $APP_DIR/.env 填入 QWEN_API_KEY 与 CM_REVIEWER_TOKEN，然后
#   systemctl enable --now cloudmaster
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/cloudmaster}"
REPO_URL="${REPO_URL:-https://github.com/GAODUMACHINE/CLOUDMASTER20260910.git}"
BRANCH="${BRANCH:-main}"
DOMAIN="${DOMAIN:-lightcloudmaster.top}"   # 证书名取主域；www 为其 SAN
CERT_EMAIL="${CERT_EMAIL:-}"
WEBROOT="/var/www/html"
SVC_USER="cloudmaster"

step() { printf '\n=== %s ===\n' "$*"; }

[ "$(id -u)" -eq 0 ] || { echo "请以 root 运行"; exit 1; }
if [ -z "$CERT_EMAIL" ]; then
  echo "缺少 CERT_EMAIL（Let's Encrypt 通知邮箱）：CERT_EMAIL=you@example.com bash bootstrap.sh"
  exit 1
fi

step "1/8 系统依赖"
apt-get update -qq
apt-get install -y -qq python3-venv nginx certbot >/dev/null

step "2/8 代码（$BRANCH）"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch --quiet && git -C "$APP_DIR" checkout --quiet "$BRANCH"
  git -C "$APP_DIR" pull --ff-only --quiet
else
  git clone --quiet --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

step "3/8 venv 与安装"
python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -e .
# ProtectSystem=strict 下仓库只读：预编译字节码，运行期不再写 __pycache__
.venv/bin/python -m compileall -q cloudmaster scripts

step "4/8 .env 骨架（密钥不入库；不覆盖已有配置）"
if [ ! -f .env ]; then cp -n .env.example .env; fi

step "5/8 服务账号与数据目录"
id "$SVC_USER" >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$SVC_USER"
# .env 双读方：systemd（root，EnvironmentFile）+ 进程内 pydantic-settings（服务账号）
# → 640 root:cloudmaster，两端都读得到，其他用户不可见
chown root:"$SVC_USER" .env
chmod 640 .env
mkdir -p "$APP_DIR/data/private"
chown -R "$SVC_USER":"$SVC_USER" "$APP_DIR/data"

step "6/8 systemd：Web 服务 + 每日定时任务（回访交付 + 保留期清除）"
cat > /etc/systemd/system/cloudmaster.service <<UNIT
[Unit]
Description=CloudMaster FastAPI (uvicorn)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SVC_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/.venv/bin/uvicorn cloudmaster.server:app --host 127.0.0.1 --port 8000 --workers 1
Restart=on-failure
RestartSec=3
# 加固：仅 data/ 可写（密钥在 .env，root 属主 600，服务账号只读）
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=${APP_DIR}/data
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/cloudmaster-jobs.service <<UNIT
[Unit]
Description=CloudMaster daily jobs (followups + purge)

[Service]
Type=oneshot
User=${SVC_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/.venv/bin/python -m scripts.run_jobs all
UNIT

cat > /etc/systemd/system/cloudmaster-jobs.timer <<UNIT
[Unit]
Description=Run CloudMaster daily jobs

[Timer]
OnCalendar=*-*-* 09:17:00
Persistent=true

[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --quiet --now cloudmaster-jobs.timer

step "7/8 TLS 证书（webroot 签发，90 天自动续期）"
mkdir -p "$WEBROOT"
cat > /etc/nginx/sites-available/cloudmaster <<'NGINX_STAGING'
server {
    listen 80;
    listen [::]:80;
    server_name lightcloudmaster.top www.lightcloudmaster.top;
    location /.well-known/acme-challenge/ { root /var/www/html; }
    location / { return 301 https://www.lightcloudmaster.top$request_uri; }
}
NGINX_STAGING
ln -sfn /etc/nginx/sites-available/cloudmaster /etc/nginx/sites-enabled/cloudmaster
rm -f /etc/nginx/sites-enabled/default
nginx -t -q
systemctl enable --quiet --now nginx
if [ ! -d "/etc/letsencrypt/live/$DOMAIN" ]; then
  certbot certonly --webroot -w "$WEBROOT" -d "$DOMAIN" -d "www.$DOMAIN" \
    --cert-name "$DOMAIN" --non-interactive --agree-tos -m "$CERT_EMAIL"
fi
# 续期成功后自动重载 nginx
mkdir -p /etc/letsencrypt/renewal-hooks/deploy
cat > /etc/letsencrypt/renewal-hooks/deploy/cloudmaster-reload-nginx.sh <<'HOOK'
#!/bin/sh
systemctl reload nginx
HOOK
chmod +x /etc/letsencrypt/renewal-hooks/deploy/cloudmaster-reload-nginx.sh

step "8/8 正式站点配置（TLS + SSE 反代）"
install -m 644 "$APP_DIR/deploy/nginx-cloudmaster.conf" /etc/nginx/sites-available/cloudmaster
nginx -t -q && systemctl reload nginx

if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow 80,443/tcp >/dev/null
fi

cat <<DONE

装配完成。剩两步手工动作：
  1) 编辑 ${APP_DIR}/.env ：填 QWEN_API_KEY（真实模型）与 CM_REVIEWER_TOKEN（审核台）；
     上线演示期可先 CM_STUB=1 走替身。邮件通道（SMTP_*/IMAP_*）暂不填则如实关闭。
  2) systemctl enable --now cloudmaster && systemctl status cloudmaster --no-pager
验证：  curl -I https://www.${DOMAIN}/       （应 301/200，HTTPS 生效）
日志：  journalctl -u cloudmaster -f
定时任务下次执行： systemctl list-timers cloudmaster-jobs.timer
DONE
