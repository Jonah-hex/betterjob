#!/usr/bin/env bash
# BetterJob — install on Oracle Cloud Ubuntu VM (Always Free)
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/betterjob}"
REPO_URL="${REPO_URL:-https://github.com/Jonah-hex/betterjob.git}"
BETTERJOB_USER="${BETTERJOB_USER:-admin}"

echo "==> BetterJob Oracle Cloud installer"
echo "    App dir: $APP_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "==> Installing Docker..."
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker "$USER" || true
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "ERROR: docker compose plugin missing. Re-login after Docker install, then re-run."
  exit 1
fi

if [ ! -d "$APP_DIR/.git" ]; then
  echo "==> Cloning repository..."
  git clone "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR"
git pull --ff-only || true

if [ ! -f .env ]; then
  cp deploy/oracle/env.production.example .env
  echo ""
  echo "!! Edit .env with Brevo/SMTP secrets before sending emails:"
  echo "   nano $APP_DIR/.env"
  echo ""
fi

if [ ! -f deploy/oracle/nginx/.htpasswd ]; then
  echo "==> Dashboard login (nginx basic auth)"
  read -rsp "Enter password for user '$BETTERJOB_USER': " PASS
  echo ""
  HASH="$(openssl passwd -apr1 "$PASS")"
  mkdir -p deploy/oracle/nginx
  printf '%s:%s\n' "$BETTERJOB_USER" "$HASH" > deploy/oracle/nginx/.htpasswd
  chmod 644 deploy/oracle/nginx/.htpasswd
  echo "Saved deploy/oracle/nginx/.htpasswd"
fi

mkdir -p data
echo "==> Building and starting containers..."
docker compose -f docker-compose.prod.yml up -d --build

echo ""
echo "=============================================="
echo " BetterJob is running"
echo " Main:  http://$(curl -s ifconfig.me 2>/dev/null || echo YOUR_PUBLIC_IP)/"
echo " Pro:   http://$(curl -s ifconfig.me 2>/dev/null || echo YOUR_PUBLIC_IP)/pro/"
echo " Login: user=$BETTERJOB_USER + password you set"
echo "=============================================="
echo ""
echo "Useful commands:"
echo "  cd $APP_DIR && docker compose -f docker-compose.prod.yml logs -f"
echo "  cd $APP_DIR && docker compose -f docker-compose.prod.yml restart"
