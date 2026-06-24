#!/usr/bin/env bash
# BetterJob — تحديث السيرفر من GitHub بعد push من جهاز الدوام/البيت
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/betterjob}"
COMPOSE_FILE="docker-compose.prod.yml"

echo "==> BetterJob Oracle update"
echo "    Dir: $APP_DIR"

cd "$APP_DIR"

if [ ! -d .git ]; then
  echo "ERROR: $APP_DIR is not a git repo. Clone first:"
  echo "  git clone https://github.com/Jonah-hex/betterjob.git"
  exit 1
fi

echo "==> git pull"
git pull --ff-only origin master

if [ -f requirements.txt ]; then
  echo "==> (optional) rebuild if Dockerfile/requirements changed"
fi

echo "==> docker compose restart"
docker compose -f "$COMPOSE_FILE" up -d --build

echo ""
echo "=============================================="
echo " Done."
echo " Main:  http://$(curl -4 -s ifconfig.me 2>/dev/null || echo YOUR_PUBLIC_IP)/"
echo " Pro:   http://$(curl -4 -s ifconfig.me 2>/dev/null || echo YOUR_PUBLIC_IP)/pro/"
echo " Logs:  cd $APP_DIR && docker compose -f $COMPOSE_FILE logs -f"
echo "=============================================="
