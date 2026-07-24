#!/usr/bin/env bash
set -e

REPO="$(cd "$(dirname "$0")" && pwd)"
mkdir -p ~/.local/bin ~/.config/systemd/user ~/.config/pomowatcher
ln -sf "$REPO/pomowatcher_sync_server.py" ~/.local/bin/pomowatcher_sync_server.py
ln -sf "$REPO/pomowatcher-sync.service" ~/.config/systemd/user/pomowatcher-sync.service

if [ ! -f ~/.config/pomowatcher/server.env ]; then
  TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  printf 'POMOWATCHER_SYNC_TOKEN=%s\n' "$TOKEN" > ~/.config/pomowatcher/server.env
  chmod 600 ~/.config/pomowatcher/server.env
fi

systemctl --user daemon-reload
systemctl --user enable --now pomowatcher-sync.service
sudo loginctl enable-linger "$USER"
echo "同期サーバーを起動しました"
echo "接続トークン: ~/.config/pomowatcher/server.env"
