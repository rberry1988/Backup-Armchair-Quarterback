#!/usr/bin/env bash
# Deploys Backup Armchair Quarterback to the current machine (an Ubuntu
# Proxmox LXC container or any Ubuntu/Debian host) as a systemd service
# behind nginx. Safe to re-run after a `git pull` to deploy an update —
# it won't touch an existing backend/.env or the SQLite database.
#
# Usage: clone this repo somewhere (e.g. ~/backup-armchair-quarterback),
# then run: sudo bash deploy/install.sh
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this with sudo: sudo bash deploy/install.sh" >&2
    exit 1
fi

APP_NAME="backup-armchair-quarterback"
APP_USER="baq"
APP_DIR="/opt/${APP_NAME}"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Installing system packages (python3, node, nginx, rsync)"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip nodejs npm nginx rsync

echo "==> Creating service user ($APP_USER)"
if ! id "$APP_USER" &>/dev/null; then
    useradd --system --no-create-home --shell /usr/sbin/nologin "$APP_USER"
fi

echo "==> Syncing app source to $APP_DIR"
mkdir -p "$APP_DIR"
# No --delete: backend/.env and backend/data (the SQLite db + nflverse
# cache) live only in the destination, never in the source checkout, so
# --delete would wipe them on every re-run. Leftover stale files from old
# checkouts are a non-issue for how this app is deployed.
rsync -a \
    --exclude 'backend/.venv' \
    --exclude 'backend/data' \
    --exclude '__pycache__' \
    --exclude 'frontend/node_modules' \
    --exclude 'frontend/dist' \
    --exclude '.git' \
    "$SOURCE_DIR"/ "$APP_DIR"/

echo "==> Setting ownership"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

echo "==> Setting up backend virtualenv"
if [ ! -d "$APP_DIR/backend/.venv" ]; then
    sudo -u "$APP_USER" python3 -m venv "$APP_DIR/backend/.venv"
fi
sudo -u "$APP_USER" "$APP_DIR/backend/.venv/bin/pip" install -q --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/backend/.venv/bin/pip" install -q -r "$APP_DIR/backend/requirements.txt"

echo "==> Preparing backend/.env"
if [ ! -f "$APP_DIR/backend/.env" ]; then
    JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
    sudo -u "$APP_USER" tee "$APP_DIR/backend/.env" > /dev/null <<EOF
DATABASE_URL=sqlite:///./data/fantasy.db
JWT_SECRET=${JWT_SECRET}
CORS_ORIGINS=http://localhost
EOF
    echo "    Generated a new JWT_SECRET in $APP_DIR/backend/.env"
else
    echo "    Found existing backend/.env — leaving it as-is"
fi
sudo -u "$APP_USER" mkdir -p "$APP_DIR/backend/data"

echo "==> Building frontend (this can take a minute)"
sudo -u "$APP_USER" bash -c "cd '$APP_DIR/frontend' && npm install --no-fund --no-audit --silent && npm run build --silent"

echo "==> Installing systemd service"
sed "s|__APP_DIR__|$APP_DIR|g; s|__APP_USER__|$APP_USER|g" \
    "$APP_DIR/deploy/backup-armchair-quarterback.service.template" \
    > "/etc/systemd/system/${APP_NAME}.service"
systemctl daemon-reload
systemctl enable --now "${APP_NAME}"
systemctl restart "${APP_NAME}"   # pick up a fresh git pull's code even if the unit already existed

echo "==> Installing nginx site"
sed "s|__APP_DIR__|$APP_DIR|g" \
    "$APP_DIR/deploy/nginx.conf.template" \
    > "/etc/nginx/sites-available/${APP_NAME}"
ln -sf "/etc/nginx/sites-available/${APP_NAME}" "/etc/nginx/sites-enabled/${APP_NAME}"
if [ -e /etc/nginx/sites-enabled/default ]; then
    echo "    Disabling the default nginx site"
    rm -f /etc/nginx/sites-enabled/default
fi
nginx -t
systemctl reload nginx 2>/dev/null || systemctl restart nginx

IP="$(hostname -I | awk '{print $1}')"
echo
echo "==> Done."
echo "    App:     http://${IP}/"
echo "    Backend: systemctl status ${APP_NAME}"
echo "    Logs:    journalctl -u ${APP_NAME} -f"
echo
echo "If ufw is active, allow HTTP: sudo ufw allow 80/tcp"
echo "To deploy an update: git pull in $SOURCE_DIR, then re-run this script."
