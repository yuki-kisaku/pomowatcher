#!/usr/bin/env bash
set -e
REPO="$(cd "$(dirname "$0")" && pwd)"

echo "==> シンボリックリンクを張る"
mkdir -p ~/.local/bin ~/.config/systemd/user
ln -sf "$REPO/pomowatcher.py"      ~/.local/bin/pomowatcher.py
ln -sf "$REPO/pomowatcher.service" ~/.config/systemd/user/pomowatcher.service

echo "==> udev ルールを配置（sudo パスワード要求あり）"
sudo cp "$REPO/99-pomowatcher.rules" /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=input

echo "==> systemd ユーザーサービスを起動"
systemctl --user daemon-reload
systemctl --user enable --now pomowatcher

echo "==> 完了。状態: $(systemctl --user is-active pomowatcher)"
