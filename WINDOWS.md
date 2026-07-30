# Windows 11版の使い方

Windows 11版は、キーボードやマウスの操作から作業時間を自動で数えます。
タイマーは画面右下へ常に手前で表示され、位置は固定です。

## インストール

PowerShellを開き、このリポジトリのフォルダーで次を実行します。

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

`install.ps1`は次の作業を自動で行います。

- Python 3.10以上がなければPython 3.13をインストール
- BGM再生用のmpvをインストール
- Pomowatcher専用のPython環境と必要パッケージを作成
- Windowsへログインしたときの自動起動を登録
- Pomowatcherを起動

インストール後は、画面右下に `○ 50:00` が表示されます。
自動起動は現在のリポジトリを参照するため、インストール後にリポジトリのフォルダーを移動しないでください。

## 表示と操作

- `○ 50:00`から作業時間に合わせて残り時間が減ります。
- 50分になるとWindows通知と通知音で休憩を促します。
- そのまま休憩せず操作を続けている場合は、5分ごとに同じ通知を出し直します。
- 10分間操作しないと休憩完了と判断し、次の50分へ戻ります。
- 通知領域のPomowatcherアイコンを左クリックまたは右クリックすると、リセット、停止、再起動、BGM操作、終了ができます。

## BGM

`C:\Users\ユーザー名\Music\pomodoro-bgm\`へ音声ファイルを置くと、作業中にmpvでシャッフル再生します。
単一ファイルの場合は、`pomodoro-bgm.mp3`のようにMusicフォルダーへ置きます。

ChromeのYouTubeやSpotifyなど、Windowsのメディア欄に表示されるほかの音楽・動画を再生すると、BGMを自動停止します。ほかのメディアを停止すると、作業中であればBGMを再開します。

YouTubeからBGMを取得するコマンドはWindows版に含まれません。

## 設定とログ

- 設定: `%LOCALAPPDATA%\pomowatcher\settings.json`
- ログ: `%LOCALAPPDATA%\pomowatcher\pomowatcher.log`

## 自動起動を解除する

通知領域のPomowatcherアイコンから「終了」を選び、次のファイルを削除します。

```text
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Pomowatcher.lnk
```

専用のPython環境も不要な場合は、リポジトリ内の`.venv-windows`フォルダーを削除できます。BGM、設定、ログは削除されません。
