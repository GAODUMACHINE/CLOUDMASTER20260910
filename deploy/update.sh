#!/usr/bin/env bash
# CloudMaster 例行更新（服务器上 root 执行）：拉最新代码 → 重装 → 预编译 → 重启服务。
# 用法： APP_DIR=/opt/cloudmaster bash update.sh    （缺省 /opt/cloudmaster）
# .env 与 data/ 不受影响（均不入库）；回滚 = git -C "$APP_DIR" checkout <旧提交> 后重跑本脚本。
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/cloudmaster}"
cd "$APP_DIR"

git pull --ff-only
.venv/bin/pip install --quiet -e .
.venv/bin/python -m compileall -q cloudmaster scripts
systemctl restart cloudmaster
systemctl --no-pager --lines=5 status cloudmaster
