#!/usr/bin/env bash
# LightCloudMaster 例行更新（服务器上 root 执行）：拉最新代码 → 重装 → 预编译 → 重启服务。
# 用法： APP_DIR=/opt/lightcloudmaster bash update.sh    （缺省 /opt/lightcloudmaster）
# .env 与 data/ 不受影响（均不入库）；回滚 = git -C "$APP_DIR" checkout <旧提交> 后重跑本脚本。
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/lightcloudmaster}"
cd "$APP_DIR"

git pull --ff-only
.venv/bin/pip install --quiet -e .
.venv/bin/python -m compileall -q lightcloudmaster scripts
systemctl restart lightcloudmaster
systemctl --no-pager --lines=5 status lightcloudmaster
