#!/usr/bin/env bash
set -e

REPO="$(cd "$(dirname "$0")" && pwd)"
VENV="$HOME/Library/Application Support/Pomowatcher/venv"
AGENT="$HOME/Library/LaunchAgents/dev.pomowatcher.app.plist"
CLIENT_ENV="$HOME/.config/pomowatcher/client.env"

python3 -m venv "$VENV"
"$VENV/bin/pip" install -r "$REPO/requirements-macos.txt"
mkdir -p "$(dirname "$AGENT")"
SYNC_URL=""
SYNC_TOKEN=""
if [ -f "$CLIENT_ENV" ]; then
  SYNC_URL="$(sed -n 's/^POMOWATCHER_SYNC_URL=//p' "$CLIENT_ENV" | head -n 1)"
  SYNC_TOKEN="$(sed -n 's/^POMOWATCHER_SYNC_TOKEN=//p' "$CLIENT_ENV" | head -n 1)"
fi
sed \
  -e "s|__PYTHON__|$VENV/bin/python3|g" \
  -e "s|__SCRIPT__|$REPO/pomowatcher_macos.py|g" \
  -e "s|__SYNC_URL__|$SYNC_URL|g" \
  -e "s|__SYNC_TOKEN__|$SYNC_TOKEN|g" \
  "$REPO/macos/dev.pomowatcher.app.plist" > "$AGENT"
launchctl bootout "gui/$(id -u)" "$AGENT" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$AGENT"
echo "Pomowatcher macOS版を起動しました"
