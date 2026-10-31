#!/usr/bin/env bash
#
# Set up (or update) TaskFlow on a fresh Ubuntu 24.04 server.
#
# Usage (on the server, as the default `ubuntu` user):
#   REPO_URL=https://github.com/<you>/<repo>.git bash setup_server.sh
#
# Safe to run again: it pulls the latest code, reinstalls dependencies and
# restarts the app. Existing secrets and database data are kept.
set -euo pipefail

REPO_URL="${REPO_URL:?Set REPO_URL to the GitHub clone URL}"
BRANCH="${BRANCH:-main}"
APP_USER="taskflow"
APP_DIR="/opt/taskflow"
ENV_DIR="/etc/taskflow"
ENV_FILE="$ENV_DIR/taskflow.env"
DB_NAME="taskflow"
DB_USER="taskflow"

log() { echo -e "\n==> $*"; }

log "Installing system packages"
sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    python3 python3-venv python3-pip git nginx postgresql

log "Making sure PostgreSQL starts on boot"
sudo systemctl enable --now postgresql

log "Creating app user '$APP_USER'"
if ! id "$APP_USER" >/dev/null 2>&1; then
    sudo useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi

log "Fetching code from $REPO_URL ($BRANCH)"
if [ -d "$APP_DIR/.git" ]; then
    sudo -u "$APP_USER" git -C "$APP_DIR" fetch --depth 1 origin "$BRANCH"
    sudo -u "$APP_USER" git -C "$APP_DIR" reset --hard "origin/$BRANCH"
else
    sudo mkdir -p "$APP_DIR"
    sudo chown "$APP_USER:$APP_USER" "$APP_DIR"
    sudo -u "$APP_USER" git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
sudo chmod 755 "$APP_DIR"   # lets Nginx read app/static

log "Installing Python dependencies"
sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --quiet --no-cache-dir --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --quiet --no-cache-dir -r "$APP_DIR/requirements.txt"

# Secrets are generated once on the server and never leave it.
if [ ! -f "$ENV_FILE" ]; then
    log "Generating secrets and creating database '$DB_NAME'"
    DB_PASSWORD="$(openssl rand -hex 24)"
    SECRET_KEY="$(openssl rand -hex 32)"

    if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1; then
        ROLE_SQL="ALTER ROLE $DB_USER WITH LOGIN PASSWORD :'pw';"
    else
        ROLE_SQL="CREATE ROLE $DB_USER WITH LOGIN PASSWORD :'pw';"
    fi
    # Password is passed as a psql variable via stdin, so it never appears
    # in the process list or shell history.
    echo "$ROLE_SQL" | sudo -u postgres psql -v ON_ERROR_STOP=1 -q -v pw="$DB_PASSWORD"
    if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1; then
        sudo -u postgres createdb --owner "$DB_USER" "$DB_NAME"
    fi

    sudo mkdir -p "$ENV_DIR"
    sudo tee "$ENV_FILE" >/dev/null <<EOF
APP_ENV=production
SECRET_KEY=$SECRET_KEY
DB_HOST=localhost
DB_PORT=5432
DB_NAME=$DB_NAME
DB_USER=$DB_USER
DB_PASSWORD=$DB_PASSWORD
DB_CONNECT_TIMEOUT=5
LOG_LEVEL=INFO
SESSION_COOKIE_SECURE=false
EOF
    sudo chown root:"$APP_USER" "$ENV_FILE"
    sudo chmod 640 "$ENV_FILE"
else
    log "Keeping existing secrets in $ENV_FILE"
fi

log "Creating database tables"
sudo -u "$APP_USER" bash -c "set -a; source '$ENV_FILE'; cd '$APP_DIR' && .venv/bin/flask --app run init-db"

log "Installing systemd service"
sudo cp "$APP_DIR/deploy/taskflow.service" /etc/systemd/system/taskflow.service
sudo systemctl daemon-reload
sudo systemctl enable taskflow
sudo systemctl restart taskflow

log "Configuring Nginx"
sudo cp "$APP_DIR/deploy/nginx-taskflow.conf" /etc/nginx/sites-available/taskflow
sudo ln -sf /etc/nginx/sites-available/taskflow /etc/nginx/sites-enabled/taskflow
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl enable nginx
sudo systemctl reload nginx || sudo systemctl restart nginx

log "Checking health"
for i in $(seq 1 15); do
    if curl -fsS http://127.0.0.1/health; then
        echo -e "\n\nTaskFlow is up."
        exit 0
    fi
    sleep 2
done
echo "Health check failed. Inspect logs with: sudo journalctl -u taskflow -n 50" >&2
exit 1
