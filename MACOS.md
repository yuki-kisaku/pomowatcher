# macOS版

macOS版は、Ubuntu版と同じタイマー、BGM、メニュー操作をmacOSのメニューバーで
利用するための常駐アプリです。

## 必要なもの

- macOS 13以降
- Python 3
- Homebrew版のmpv

```bash
brew install python mpv
./install-macos.sh
```

メニューバーに `○ 50:00` が表示されます。BGMは
`~/Music/pomodoro-bgm` フォルダーから読み込みます。

終了や再インストールは次のコマンドで行えます。

```bash
launchctl bootout "gui/$(id -u)" \
  "$HOME/Library/LaunchAgents/dev.pomowatcher.app.plist"
./install-macos.sh
```

macOS版では、ほかのアプリの音声再生検出は行いません。タイマー、休憩検出、
BGM、通知、同期には影響しません。
