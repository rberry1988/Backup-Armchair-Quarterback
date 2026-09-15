#!/usr/bin/env bash
# Deploys Backup Armchair Quarterback to the current machine (an Ubuntu
# Proxmox LXC container or any Ubuntu/Debian host) as a systemd service
# behind nginx. Safe to re-run — it won't touch an existing backend/.env
# or the SQLite database, and picks up new commits, dependencies, and a
# rebuilt frontend each time.
#
# Usage: clone this repo somewhere (e.g. ~/backup-armchair-quarterback),
# then run: sudo bash deploy/install.sh
# That original clone (SOURCE_DIR below) only matters for the very first
# run, to learn which remote/branch to deploy — the actual app directory
# ($APP_DIR, /opt/backup-armchair-quarterback) becomes its own independent
# git checkout from then on, which is what lets it update itself later
# (see the Admin tab's Update button).
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this with sudo: sudo bash deploy/install.sh" >&2
    exit 1
fi

APP_NAME="backup-armchair-quarterback"
APP_USER="baq"
APP_DIR="/opt/${APP_NAME}"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Installing system packages (node, nginx)"
apt-get update -qq
apt-get install -y -qq nodejs npm nginx curl ca-certificates

# Pin the backend to a specific Python version rather than trusting
# whatever `python3` the OS happens to default to. A brand-new default
# (e.g. 3.14 on a very recent distro) can predate prebuilt wheels for
# some of our pinned dependencies, and pydantic-core's build tooling
# (pyo3) outright refuses to compile against a Python newer than 3.13
# even with a working Rust toolchain on hand — confirmed against a real
# 3.14-only host. 3.12 and 3.11 both have full wheel coverage for
# everything in requirements.txt.
PYTHON_BIN=""
for candidate in python3.12 python3.11; do
    if apt-get install -y -qq "$candidate" "${candidate}-venv" 2>/dev/null; then
        PYTHON_BIN="$candidate"
        break
    fi
done
if [ -z "$PYTHON_BIN" ]; then
    echo "    Neither python3.12 nor python3.11 available from apt; will fetch a portable"
    echo "    Python 3.12 via uv once the service user/directory exist below"
fi

echo "==> Creating service user ($APP_USER)"
if ! id "$APP_USER" &>/dev/null; then
    # --home-dir here (not a separate /home/baq, never created since
    # --no-create-home) points $HOME at $APP_DIR once it exists below —
    # so pip/npm's caches land somewhere already writable by this user,
    # instead of failing outright when they try to use a home directory
    # that doesn't exist.
    useradd --system --no-create-home --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
else
    # Fix up a pre-existing install from before this was set correctly.
    usermod --home "$APP_DIR" "$APP_USER" 2>/dev/null || true
fi

echo "==> Setting up app directory at $APP_DIR"
# $APP_DIR is a git checkout in its own right (not a copy synced from
# $SOURCE_DIR) specifically so the running app can update itself later
# via a plain `git pull` in a directory it already owns — see the Admin
# tab's Update button / app/deploy_service.py. That needs no new
# permissions beyond what this service already has.
if [ -d "$APP_DIR/.git" ]; then
    echo "    Already a git checkout — pulling the latest commit"
    # Runs as $APP_USER, not root: $APP_DIR is owned by $APP_USER from the
    # last run's chown below, and git (2.35.2+) refuses to operate on a
    # repo owned by a different user ("dubious ownership" protection,
    # CVE-2022-24765) — running this as root would fail on every re-run.
    sudo -u "$APP_USER" git -C "$APP_DIR" pull --ff-only
elif [ -d "$APP_DIR" ] && [ -n "$(ls -A "$APP_DIR" 2>/dev/null)" ]; then
    echo "    Found an existing install from before this script deployed via git clone."
    echo "    Migrating it in place: backend/.env and backend/data are kept, everything"
    echo "    else is replaced by a fresh clone (deployed code was always meant to just"
    echo "    be a checkout, so nothing else there is expected to differ from git)."
    REMOTE_URL="$(git -C "$SOURCE_DIR" remote get-url origin)"
    BRANCH="$(git -C "$SOURCE_DIR" rev-parse --abbrev-ref HEAD)"
    # Clone into a fresh staging directory first and only touch $APP_DIR
    # once that succeeds — if the clone fails partway (network blip, bad
    # branch, disk full), the old $APP_DIR and its .env/data are left
    # completely untouched instead of being deleted with no way back.
    STAGING_DIR="$(mktemp -d)/checkout"
    git clone --branch "$BRANCH" "$REMOTE_URL" "$STAGING_DIR"
    mkdir -p "$STAGING_DIR/backend"
    [ -f "$APP_DIR/backend/.env" ] && mv "$APP_DIR/backend/.env" "$STAGING_DIR/backend/.env"
    [ -d "$APP_DIR/backend/data" ] && mv "$APP_DIR/backend/data" "$STAGING_DIR/backend/data"
    rm -rf "$APP_DIR"
    mv "$STAGING_DIR" "$APP_DIR"
    rmdir "$(dirname "$STAGING_DIR")" 2>/dev/null || true
else
    REMOTE_URL="$(git -C "$SOURCE_DIR" remote get-url origin)"
    BRANCH="$(git -C "$SOURCE_DIR" rev-parse --abbrev-ref HEAD)"
    echo "    Cloning $REMOTE_URL ($BRANCH) into $APP_DIR"
    git clone --branch "$BRANCH" "$REMOTE_URL" "$APP_DIR"
fi

echo "==> Setting ownership"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

if [ -z "$PYTHON_BIN" ]; then
    echo "==> Fetching a portable Python 3.12 via uv (apt had neither python3.12 nor python3.11)"
    # uv (astral.sh) ships prebuilt CPython builds independent of whatever
    # this OS's own package repos carry — the only reliable option on a
    # release that doesn't package an older Python at all. Run as
    # $APP_USER (whose $HOME is $APP_DIR, already owned by it) rather than
    # root, so the venv step right below — which also runs as $APP_USER —
    # can actually read and execute the interpreter uv installs.
    sudo -u "$APP_USER" bash -c "curl -LsSf https://astral.sh/uv/install.sh | sh"
    sudo -u "$APP_USER" "$APP_DIR/.local/bin/uv" python install 3.12
    PYTHON_BIN="$(sudo -u "$APP_USER" "$APP_DIR/.local/bin/uv" python find 3.12)"
fi
echo "    Using $PYTHON_BIN for the backend virtualenv"

echo "==> Setting up backend virtualenv"
if [ -d "$APP_DIR/backend/.venv" ]; then
    # A venv built by an earlier run against a different Python (e.g. the
    # OS's own too-new python3, before this script started pinning one)
    # needs recreating rather than reused, or pip install below would hit
    # the exact same wheel-availability problem all over again.
    existing_version="$("$APP_DIR/backend/.venv/bin/python3" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "unknown")"
    wanted_version="$("$PYTHON_BIN" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    if [ "$existing_version" != "$wanted_version" ]; then
        echo "    Existing venv uses Python $existing_version; recreating with $wanted_version"
        rm -rf "$APP_DIR/backend/.venv"
    fi
fi
if [ ! -d "$APP_DIR/backend/.venv" ]; then
    sudo -u "$APP_USER" "$PYTHON_BIN" -m venv "$APP_DIR/backend/.venv"
fi
sudo -u "$APP_USER" "$APP_DIR/backend/.venv/bin/pip" install -q --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/backend/.venv/bin/pip" install -q -r "$APP_DIR/backend/requirements.txt"

echo "==> Preparing backend/.env"
FRESH_INSTALL=0
if [ ! -f "$APP_DIR/backend/.env" ]; then
    FRESH_INSTALL=1
    JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
    sudo -u "$APP_USER" tee "$APP_DIR/backend/.env" > /dev/null <<EOF
DATABASE_URL=sqlite:///./data/fantasy.db
JWT_SECRET=${JWT_SECRET}
CORS_ORIGINS=http://localhost
ENABLE_SELF_UPDATE=true
ADMIN_EMAILS=admin@example.com
EOF
    echo "    Generated a new JWT_SECRET in $APP_DIR/backend/.env"
else
    echo "    Found existing backend/.env — leaving it as-is"
    # Self-update is safe specifically because this script now deploys via
    # a git checkout it owns (see above) — add it to an existing .env from
    # before that was true only if it's not already set either way, so a
    # deliberate ENABLE_SELF_UPDATE=false from an admin is never overridden.
    if ! grep -q '^ENABLE_SELF_UPDATE=' "$APP_DIR/backend/.env"; then
        echo "ENABLE_SELF_UPDATE=true" | sudo -u "$APP_USER" tee -a "$APP_DIR/backend/.env" > /dev/null
        echo "    Added ENABLE_SELF_UPDATE=true (new since your last install)"
    fi
    # No ADMIN_EMAILS backfill here on purpose — this branch means you've
    # already been through setup once, so whatever admin(s) you already
    # configured (or deliberately didn't) stands; a fresh install is the
    # only time it's safe to assume nobody's an admin yet.
fi
# Holds the session signing key and any API keys, so keep it readable only
# by the service account rather than every local user on the box.
chmod 600 "$APP_DIR/backend/.env"
chown "$APP_USER:$APP_USER" "$APP_DIR/backend/.env"
sudo -u "$APP_USER" mkdir -p "$APP_DIR/backend/data"

ADMIN_EMAIL=""
ADMIN_PASSWORD=""
if [ "$FRESH_INSTALL" = "1" ]; then
    echo "==> Creating a default admin account"
    BOOTSTRAP_RESULT="$(cd "$APP_DIR/backend" && sudo -u "$APP_USER" "$APP_DIR/backend/.venv/bin/python3" -m app.bootstrap_admin)"
    case "$BOOTSTRAP_RESULT" in
        created:*)
            ADMIN_EMAIL="$(echo "$BOOTSTRAP_RESULT" | cut -d: -f2)"
            ADMIN_PASSWORD="$(echo "$BOOTSTRAP_RESULT" | cut -d: -f3)"
            echo "    Created $ADMIN_EMAIL — password printed at the end of this script"
            ;;
        exists:*)
            echo "    Account already exists — leaving it as-is"
            ;;
        *)
            echo "    WARNING: couldn't create a default admin account (${BOOTSTRAP_RESULT#error:})."
            echo "    Register your own account from the login page and add its email to"
            echo "    ADMIN_EMAILS in backend/.env instead."
            ;;
    esac
fi

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
if [ -n "$ADMIN_PASSWORD" ]; then
    echo
    echo "    Log in at http://${IP}/ with:"
    echo "      Email:    $ADMIN_EMAIL"
    echo "      Password: $ADMIN_PASSWORD"
    echo "    This is shown once — write it down now. Change it from the Account tab"
    echo "    after logging in, or reset it later via the Admin tab if you lose it."
fi
echo
echo "If ufw is active, allow HTTP: sudo ufw allow 80/tcp"
echo "To deploy an update: use the Admin tab's Update button (needs ENABLE_SELF_UPDATE=true"
echo "in backend/.env — see README), or manually: git -C $APP_DIR pull --ff-only, then"
echo "re-run this script to pick up any new dependencies."
