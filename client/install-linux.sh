#!/usr/bin/env bash
# Install Remote Power as a background user systemd service (starts at login).
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
PY="$(command -v python3 || true)"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT="$UNIT_DIR/remote-power-listener.service"

[ -n "$PY" ] || { echo "python3 not found. Install Python 3 first."; exit 1; }
[ -f "$DIR/config.ini" ] || { echo "config.ini not found — copy config.example.ini to config.ini and add your API key first."; exit 1; }

echo "Installing 'requests'..."
"$PY" -m pip install --quiet --user requests || true

mkdir -p "$UNIT_DIR"
cat > "$UNIT" <<EOF
[Unit]
Description=Remote Power listener
After=network-online.target

[Service]
Type=simple
WorkingDirectory=$DIR
ExecStart=$PY $DIR/listener.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now remote-power-listener.service

echo
echo "Installed. Running in the background now and at login."
echo "Status:    systemctl --user status remote-power-listener"
echo "Logs:      journalctl --user -u remote-power-listener -f   (or $DIR/listener.log)"
echo "To remove: systemctl --user disable --now remote-power-listener && rm \"$UNIT\""
echo
echo "Tip: to keep it running even when you're not logged in:"
echo "     sudo loginctl enable-linger $USER"
