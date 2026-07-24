# Pomowatcher同期設定

Ubuntuノートで同期サーバーを起動します。

```bash
./install-sync-server.sh
hostname -I
cat ~/.config/pomowatcher/server.env
```

インストール時にユーザーサービスの常時起動も有効になるため、デスクトップへ
ログインしていない間も同期サーバーは動作します。Ubuntuノートがスリープまたは
電源オフの間は接続できません。

各端末に同期サーバーのURLと、表示されたトークンを設定します。

## Ubuntu

`~/.config/pomowatcher/client.env` を作成します。

```text
POMOWATCHER_SYNC_URL=http://UbuntuノートのIPアドレス:8765
POMOWATCHER_SYNC_TOKEN=表示されたトークン
```

設定後に再起動します。

```bash
systemctl --user restart pomowatcher
```

## Windows

ユーザー環境変数に次の2項目を設定し、Pomowatcherを再起動します。

```text
POMOWATCHER_SYNC_URL=http://UbuntuノートのIPアドレス:8765
POMOWATCHER_SYNC_TOKEN=表示されたトークン
```

## macOS

`~/.config/pomowatcher/client.env` を作成します。

```text
POMOWATCHER_SYNC_URL=http://UbuntuノートのIPアドレス:8765
POMOWATCHER_SYNC_TOKEN=表示されたトークン
```

設定後、`./install-macos.sh` をもう一度実行します。

同期サーバーが停止している間も各端末ではタイマーを利用できます。再接続後は、
操作中の端末の状態が共有されます。
