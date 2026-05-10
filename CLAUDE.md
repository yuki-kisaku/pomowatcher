# Claude 向け引き継ぎ

このプロジェクトは隔離ノートPC上で開発する。あなた（Claude Code）は SSH 経由で呼ばれて、コード修正・テスト・コミットまで自律的に行う。

## 環境

- Ubuntu Desktop 24.04 LTS, GNOME, Wayland
- ユーザ: `yuki`、passwordless sudo 設定済み
- リポジトリ: `~/ai-dev/pomowatcher/`
- インストール: `./install.sh` でシンボリックリンク + サービス起動
- `keyd` でキーリマップが動いている（重要）

## テストの回し方

1. 編集後はリンクなので即反映される。再起動だけ:
   ```bash
   systemctl --user restart pomowatcher
   ```
2. ログ確認:
   ```bash
   journalctl --user -u pomowatcher -f
   ```
3. しきい値テスト: `pomowatcher.py` 冒頭の定数を一時的に小さくする
   ```python
   WORK_THRESHOLD_SEC  = 2 * 60   # 2分で通知（テスト用）
   IDLE_THRESHOLD_SEC  = 30       # 30秒で休憩判定
   CHECK_INTERVAL_SEC  = 5
   ACTIVE_LIMIT_MS     = 5 * 1000
   ```
   テストが終わったら本番値に戻すこと。

## 既知の問題（直近セッションでハマった点）

### keyd の干渉
- Mutter IdleMonitor (`gdbus call ... GetIdletime`) は **常に 64ms 程度を返してしまう**
- 原因: keyd の仮想ポインタ (`/dev/input/event18`) が常に活動を発生させているため
- 対策: 物理デバイスを evdev で直接監視する方式に切り替え済み（`_watch_device` 関数）

### input グループ反映
- `usermod -aG input yuki` だけでは systemd --user に即座には反映されない
- `systemctl --user daemon-reexec` でも不可
- **再起動が必要**。または udev ルールの `TAG+="uaccess"` で逃げる

### 物理デバイスが keyd に grab されている可能性
- まだ完全には検証できていない
- もし `/dev/input/event2` (Magic Keyboard) や `event4` (Logitech M575) からイベントが取れない場合、keyd が `EVIOCGRAB` で排他取得している可能性がある
- その場合は keyd の仮想デバイス (`event17`/`event18`) 側を読む必要がある

## コミット規約

- Conventional Commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`
- `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>` は付ける
- テスト用しきい値の変更を本番値に戻し忘れないこと（コミット前に diff を見て確認）

## やっていいこと / やっちゃダメなこと

**やっていい:**
- `~/ai-dev/pomowatcher/` 以下の全ファイル編集
- `sudo apt install` で依存追加
- `systemctl --user restart/status pomowatcher`
- udev ルール修正（`/etc/udev/rules.d/99-pomowatcher.rules`）
- git commit / push（main ブランチ直 push でよい、PR 不要）

**やっちゃダメ:**
- ユーザのホーム以下の他プロジェクト (`~/ai-dev/pomowatcher/` 以外) を触る
- システム全体の設定変更（GDM, sshd, sudoers など）
- `git push --force`
- テスト用しきい値のままコミット
