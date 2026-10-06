#!/usr/bin/env bash
#
# One-time setup: installs a systemd timer that auto-deploys this repo whenever
# you push to the deploy branch. Run it once, as root:
#
#   sudo bash deploy/install-autodeploy.sh
#
# Change the check interval with:  INTERVAL=1min sudo bash deploy/install-autodeploy.sh
# Remove it with:                  sudo systemctl disable --now amos-autodeploy.timer
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
INTERVAL="${INTERVAL:-2min}"

cat > /etc/systemd/system/amos-autodeploy.service <<EOF
[Unit]
Description=Amos Solutions auto-deploy check
After=network-online.target

[Service]
Type=oneshot
ExecStart=/bin/bash $REPO_DIR/deploy/auto-deploy.sh
EOF

cat > /etc/systemd/system/amos-autodeploy.timer <<EOF
[Unit]
Description=Amos Solutions auto-deploy timer

[Timer]
OnBootSec=$INTERVAL
OnUnitActiveSec=$INTERVAL
AccuracySec=15s

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now amos-autodeploy.timer

echo
echo "Auto-deploy installed — checks $REPO_DIR for new commits every $INTERVAL."
echo "Watch it:   journalctl -u amos-autodeploy -f"
echo "Run now:    sudo systemctl start amos-autodeploy.service"
echo "Stop it:    sudo systemctl disable --now amos-autodeploy.timer"
