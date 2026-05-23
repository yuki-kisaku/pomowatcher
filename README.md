# pomowatcher

Ubuntu 用の自動ポモドーロタイマー。**作業時間を自動検知して 50 分経過したら通知する** デスクトップ常駐アプリ。

タイマーボタンを押す手間がいらない。GNOME パネルにアイコンが出て、進捗を可視化する。

## 機能

- 入力デバイス（キーボード・マウス）の活動から「作業中」を判定
- 50 分連続で作業すると `notify-send` でデスクトップ通知し、休憩を促す音を鳴らす
- 通知後はパネルに `Take a break!!` を表示し、**10 分以上アイドルになるまで表示し続ける**（作業を続けてもタイマーは再スタートしない）
- 10 分以上アイドルになると休憩完了とみなして次の作業サイクルへ移行
- 作業中に 10 分以上アイドルになると自動でタイマーリセット
- パネル表示: `○ → ◔ → ◑ → ◕ → ●` と残り時間で進捗表示（アイコンは表示しない）
- トレイメニュー: リセット / 停止 / 終了

## 動作環境

- Ubuntu 24.04 LTS 以降（GNOME, Wayland）
- Python 3.10+
- 物理キーボード・マウスが `/dev/input/event*` に出ていること

## 依存パッケージ

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 \
  gir1.2-ayatanaappindicator3-0.1 python3-evdev libnotify-bin libcanberra-gtk3-bin mpv yt-dlp
```

## インストール

```bash
git clone <このリポジトリ> ~/dev/pomowatcher
cd ~/dev/pomowatcher
./install.sh
sudo usermod -aG input $USER   # 初回のみ
sudo reboot                    # グループ反映＆udev反映
```

`install.sh` がやること:
- `pomowatcher.py` / `pomowatcher.service` を `~/.local/bin/` と `~/.config/systemd/user/` にシンボリックリンク
- `99-pomowatcher.rules` を `/etc/udev/rules.d/` にコピー（input デバイスへの uaccess 付与）
- systemd ユーザーサービスを enable + start

## 更新

```bash
cd ~/dev/pomowatcher
git pull
systemctl --user restart pomowatcher
```

`install.sh` を再実行する必要はない（リンクなので自動反映）。`pomowatcher.service` や udev ルールが変わったときだけ再実行。

## アンインストール

```bash
systemctl --user disable --now pomowatcher
rm ~/.local/bin/pomowatcher.py ~/.config/systemd/user/pomowatcher.service
sudo rm /etc/udev/rules.d/99-pomowatcher.rules
```

## BGM（作業中に好きな音楽を流す）

`~/Music/pomodoro-bgm/` フォルダに音声ファイルを置くと、作業中にシャッフル再生されます。
`~/Music/pomodoro-bgm.mp3` のように単一ファイルでも使えます。
短い idle 状態では曲の途中位置を保って一時停止し、作業再開を検知するとすぐ同じ位置から再開します。
10 分以上 idle で休憩確定したときと、50 分経過時は自動停止します。
トレイメニューの `BGM > 次の曲` から、シャッフル再生中の次の曲へ送れます。
トレイメニューの `BGM > ミュート` をオンにすると BGM を曲の途中位置を保って一時停止し、作業再開時も自動再生しません。
トレイメニューの `BGM > 音量 50%` などから BGM の音量を変更できます。
ミュートと音量の設定は `~/.config/pomowatcher/settings.json` に保存され、アプリ再起動後も引き継がれます。
Chrome、Firefox、動画プレイヤーなどの MPRIS 対応メディアが再生中の間は、pomowatcher の BGM を曲の途中位置を保って一時停止します。
他のメディア再生が終わると、作業中であれば BGM を同じ位置から再開します。

### pomobgm コマンド（YouTube から並列ダウンロード）

`pomobgm.sh` を source すると `pomobgm` コマンドが使えます:

```bash
# .bashrc または .zshrc に追加
source ~/dev/pomowatcher/pomobgm.sh
```

使い方:

```bash
pomobgm "https://youtube.com/..." "https://youtube.com/..." "https://youtube.com/..."
```

最大 4 並列でダウンロードします。

### 手動でダウンロードする場合

```bash
mkdir -p ~/Music/pomodoro-bgm
yt-dlp -x --audio-format mp3 -o "~/Music/pomodoro-bgm/%(title)s.%(ext)s" "URL"
```

ファイルを置き換えたら `systemctl --user restart pomowatcher` で反映されます。
`mpv` と `yt-dlp` は依存パッケージに含まれています。

## 設定（しきい値）

`pomowatcher.py` 冒頭の定数を直接編集:

```python
WORK_THRESHOLD_SEC  = 50 * 60   # 通知までの作業時間
IDLE_THRESHOLD_SEC  = 10 * 60   # 休憩とみなすアイドル時間
CHECK_INTERVAL_SEC  = 30        # チェック周期
ACTIVE_LIMIT_MS     = 30 * 1000 # 「離席中」と判定するアイドルしきい値
```

## アーキテクチャ

```
pomowatcher.py
├─ evdev で /dev/input/event* を監視（バックグラウンドスレッド）
│   ↳ 物理デバイスからの入力イベントごとに last_input_time を更新
├─ 30秒ごとに tick: idle時間 = monotonic - last_input_time
│   ↳ active なら active_seconds += 30
│   ↳ 50分到達で notify-send + 効果音 → awaiting_break 状態に入り Take a break!! を表示
│   ↳ awaiting_break 中は 10分アイドルで始めて休憩完了 → タイマーリセット
│   ↳ 作業中に 10分以上 idle で「休憩検知」→ リセット
└─ GTK + AyatanaAppIndicator3 でパネルとポップアップを描画
```

### なぜ Mutter IdleMonitor を使わないのか

GNOME 標準の `org.gnome.Mutter.IdleMonitor` は `keyd`（キーリマッパー）の仮想ポインタが生成するイベントで常にリセットされてしまうため、`keyd` 環境下では使い物にならない。物理デバイスを evdev で直読みすることで回避している。
