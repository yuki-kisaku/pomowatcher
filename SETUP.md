# 隔離PC セットアップ手順（Claude Code 向け）

このファイルを読んで実行してほしい。ただし**全部をいちからやるのではなく、まず現状を確認して、まだ終わっていない手順だけを実施すること**。

## 最初にやること: 現状確認

以下のコマンドで現在の状態を把握してから作業に入る:

```bash
# GNOME デスクトップが入っているか
dpkg -l ubuntu-desktop-minimal 2>/dev/null | grep -E "^ii" && echo "✓ 入っている" || echo "✗ 未インストール"

# 自動ログインが設定されているか
grep -E "AutomaticLoginEnable|AutomaticLogin" /etc/gdm3/custom.conf 2>/dev/null || echo "✗ 未設定"

# 依存パッケージが揃っているか
python3 -c "import gi, evdev; print('✓ OK')" 2>/dev/null || echo "✗ 不足あり"

# リポジトリが clone 済みか
ls ~/ai-dev/pomowatcher/pomowatcher.py 2>/dev/null && echo "✓ clone済み" || echo "✗ 未clone"

# サービスが動いているか
systemctl --user is-active pomowatcher 2>/dev/null || echo "✗ 未起動"

# input グループに入っているか
id | grep -q input && echo "✓ input グループあり" || echo "✗ input グループなし"
```

確認できたら、まだ `✗` になっている手順だけ以下から選んで実行する。passwordless sudo は設定済みの前提。詰まったら理由を述べて止まってよい。

---

## Phase 1: デスクトップ環境を整える

### 1-1. GNOME デスクトップ追加

```bash
sudo apt update
sudo apt install -y ubuntu-desktop-minimal
```

### 1-2. 自動ログイン設定

`/etc/gdm3/custom.conf` を編集:
```ini
[daemon]
AutomaticLoginEnable=true
AutomaticLogin=yuki
```

### 1-3. 依存パッケージ

```bash
sudo apt install -y \
  python3-gi \
  gir1.2-gtk-3.0 \
  gir1.2-ayatanaappindicator3-0.1 \
  python3-evdev \
  libnotify-bin
```

---

## Phase 2: リポジトリを展開してアプリを動かす

### 2-1. クローン

```bash
mkdir -p ~/ai-dev
git clone git@github.com:yuki-kisaku/pomowatcher.git ~/ai-dev/pomowatcher
```

### 2-2. インストール（シンボリックリンク + サービス登録）

```bash
cd ~/ai-dev/pomowatcher
./install.sh
```

### 2-3. 入力デバイスへのアクセス権を付与

```bash
sudo usermod -aG input yuki
```

---

## Phase 3: 再起動して動作確認

```bash
sudo reboot
```

再起動後に SSH で入り直して確認:

```bash
# サービスが起動しているか
systemctl --user is-active pomowatcher   # → active

# ログでアイドル検知が動いているか（30秒ほど眺める）
journalctl --user -u pomowatcher -f
```

**正常時のログ:**
- `監視開始: <デバイス名>` が複数行出る
- `idle_ms=XXX` が 30 秒ごとに出て、マウス・キーボードを動かすと小さく、放置すると増える

**もし `アクセス拒否` が全デバイスで出る場合:**
→ udev の `TAG+="uaccess"` が効いていない可能性。`CLAUDE.md` の「既知の問題」を参照して対処する。

---

## Phase 4: 動作テスト

しきい値を短くして通知 + 休憩リセットを確認する（`pomowatcher.py` 冒頭を一時変更）:

```python
WORK_THRESHOLD_SEC  = 2 * 60   # 2分で通知
IDLE_THRESHOLD_SEC  = 30       # 30秒で休憩判定
CHECK_INTERVAL_SEC  = 5
ACTIVE_LIMIT_MS     = 5 * 1000
```

```bash
systemctl --user restart pomowatcher
journalctl --user -u pomowatcher -f
```

確認後、**本番値に戻してコミット**:
```python
WORK_THRESHOLD_SEC  = 50 * 60
IDLE_THRESHOLD_SEC  = 10 * 60
CHECK_INTERVAL_SEC  = 30
ACTIVE_LIMIT_MS     = 30 * 1000
```

```bash
git add pomowatcher.py
git commit -m "test: テスト用しきい値に戻す"
git push
```

---

## 完了条件

- [ ] `systemctl --user is-active pomowatcher` → `active`
- [ ] ログの `idle_ms=` がマウスを動かすと減り、放置すると増える
- [ ] 2分テストで `作業50分経過` 通知が届く
- [ ] 30秒放置で `休憩検知 → リセット` がログに出る

全部通ったら開発フェーズへ。詳細は `CLAUDE.md` を参照。
