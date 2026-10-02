#!/usr/bin/env bash
# Install Remote Power as a background LaunchAgent (starts at login, no window).
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
PY="$(command -v python3 || true)"
LABEL="fyi.amos.remotepower"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

[ -n "$PY" ] || { echo "python3 not found. Install Python 3 first."; exit 1; }
[ -f "$DIR/config.ini" ] || { echo "config.ini not found — copy config.example.ini to config.ini and add your API key first."; exit 1; }

echo "Installing 'requests'..."
"$PY" -m pip install --quiet --user requests || true

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PY</string>
        <string>$DIR/listener.py</string>
    </array>
    <key>WorkingDirectory</key><string>$DIR</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>$DIR/launchd.log</string>
    <key>StandardErrorPath</key><string>$DIR/launchd.log</string>
</dict>
</plist>
EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo
echo "Installed. Remote Power runs in the background now and at every login."
echo "Logs:      $DIR/listener.log"
echo "To remove: launchctl unload \"$PLIST\" && rm \"$PLIST\""
