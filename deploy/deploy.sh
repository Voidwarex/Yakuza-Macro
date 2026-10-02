#!/usr/bin/env bash
#
# Deploy Remote Power on the server (run this over SSH, on the box that
# serves amos.fyi). It does two things:
#
#   1. Publishes the new website/index.html to the amos.fyi web root.
#   2. Installs + (re)starts the relay behind nginx at api.amos.fyi.
#
# First time:
#   git clone https://github.com/Voidwarex/Yakuza-Macro.git ~/remote-power
#   cd ~/remote-power
#   git checkout claude/remote-pc-shutdown-app-2c01dc   # or main, once merged
#   # put your secrets in /etc/remote-power.env (see server/config.example.env)
#   sudo bash deploy/deploy.sh
#
# Later updates:
#   cd ~/remote-power && git pull && sudo bash deploy/deploy.sh
#
set -euo pipefail

# ---- edit these to match your server ----
WEB_ROOT="/var/www/amos"            # where nginx serves amos.fyi from
APP_DIR="/opt/remote-power"          # where the relay lives/runs
ENV_FILE="/etc/remote-power.env"     # ADMIN_PASSWORD, SECRET_KEY, etc.
SERVICE="remote-power"               # systemd unit name
RUN_USER="www-data"                  # user the relay runs as
# -----------------------------------------

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Publishing website to $WEB_ROOT"
install -d "$WEB_ROOT"
cp -r "$REPO_DIR"/website/. "$WEB_ROOT"/   # html, og.png and any other assets

echo "==> Installing relay into $APP_DIR"
install -d "$APP_DIR"
cp -r "$REPO_DIR/server/." "$APP_DIR/"

echo "==> Python dependencies"
python3 -m pip install --quiet -r "$APP_DIR/requirements.txt"

if [ ! -f "$ENV_FILE" ]; then
    echo "!! $ENV_FILE not found. Create it before starting the service:"
    echo "   cp $REPO_DIR/server/config.example.env $ENV_FILE  &&  edit it"
    echo "   (set a strong ADMIN_PASSWORD and a random SECRET_KEY)"
fi

echo "==> Installing systemd unit"
sed -e "s#/opt/remote-power/server#$APP_DIR#g" \
    -e "s#/etc/remote-power.env#$ENV_FILE#g" \
    -e "s#^User=.*#User=$RUN_USER#g" \
    "$REPO_DIR/deploy/remote-power.service" > "/etc/systemd/system/$SERVICE.service"

# Let the relay write its database directory.
chown -R "$RUN_USER":"$RUN_USER" "$APP_DIR" || true

systemctl daemon-reload
systemctl enable "$SERVICE"
systemctl restart "$SERVICE"

echo "==> Reloading nginx"
nginx -t && systemctl reload nginx

echo "==> Done."
echo "    Website : https://amos.fyi"
echo "    Panel   : https://api.amos.fyi"
systemctl --no-pager --full status "$SERVICE" | head -n 6 || true
