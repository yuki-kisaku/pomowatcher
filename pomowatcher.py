#!/usr/bin/env python3
import atexit
import os
import subprocess
import logging
import sys
import time
import threading

import evdev
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import Gtk, GLib, AyatanaAppIndicator3 as AppIndicator3

# --- 設定 ---
WORK_THRESHOLD_SEC  = 50 * 60
IDLE_THRESHOLD_SEC  = 10 * 60
CHECK_INTERVAL_SEC  = 30
ACTIVE_LIMIT_MS     = 30 * 1000

# 作業中 BGM
# 優先順:
#   1. ~/Music/pomodoro-bgm/ ディレクトリ → 中の全曲をシャッフル再生
#   2. ~/Music/pomodoro-bgm.mp3 など単一ファイル → ループ再生
# いずれも存在しない場合は何も再生しない
BGM_DIR = os.path.expanduser("~/Music/pomodoro-bgm")
BGM_FILE_CANDIDATES = [
    f"{BGM_DIR}.mp3",
    f"{BGM_DIR}.ogg",
    f"{BGM_DIR}.flac",
    f"{BGM_DIR}.m4a",
    f"{BGM_DIR}.opus",
    f"{BGM_DIR}.webm",
]
AUDIO_EXTENSIONS = {".mp3", ".ogg", ".flac", ".m4a", ".opus", ".webm", ".wav", ".aac"}
BLANK_ICON_NAME = "pomowatcher-blank"
BLANK_ICON_DIR = os.path.expanduser("~/.cache/pomowatcher")
BLANK_ICON_PATH = os.path.join(BLANK_ICON_DIR, f"{BLANK_ICON_NAME}.svg")

logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                    format="%(asctime)s %(message)s", datefmt="%H:%M:%S")


def _ensure_blank_icon():
    os.makedirs(BLANK_ICON_DIR, exist_ok=True)
    if not os.path.exists(BLANK_ICON_PATH):
        with open(BLANK_ICON_PATH, "w", encoding="utf-8") as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>\n')
    return BLANK_ICON_NAME


# --- BGM 管理 ---

_bgm_process = None
_bgm_lock = threading.Lock()


def _find_bgm_target():
    """BGM の再生対象を返す。
    - ディレクトリが存在すれば "dir:/path"
    - 単一ファイルがあれば "file:/path"
    - なければ None
    """
    if os.path.isdir(BGM_DIR):
        audio_files = sorted(
            f for f in os.listdir(BGM_DIR)
            if os.path.splitext(f)[1].lower() in AUDIO_EXTENSIONS
        )
        if audio_files:
            return ("dir", BGM_DIR)
    for path in BGM_FILE_CANDIDATES:
        if os.path.isfile(path):
            return ("file", path)
    return None


def _start_bgm():
    """mpv を起動する。すでに再生中なら何もしない。"""
    global _bgm_process
    target = _find_bgm_target()
    if target is None:
        logging.debug(f"BGM が見つかりません: {BGM_DIR}")
        return
    kind, path = target
    with _bgm_lock:
        if _bgm_process is not None and _bgm_process.poll() is None:
            return
        try:
            if kind == "dir":
                cmd = ["mpv", "--no-video", "--shuffle", "--loop-playlist=inf", "--really-quiet", path]
            else:
                cmd = ["mpv", "--no-video", "--loop-file=inf", "--really-quiet", path]
            _bgm_process = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            logging.info(f"BGM 再生開始: {path} ({kind})")
        except FileNotFoundError:
            logging.warning("mpv が見つかりません。sudo apt install mpv でインストールしてください")


def _stop_bgm():
    """再生中の mpv を停止する。"""
    global _bgm_process
    with _bgm_lock:
        if _bgm_process is not None:
            p = _bgm_process
            _bgm_process = None
            try:
                p.terminate()
                p.wait(timeout=2)
            except (subprocess.TimeoutExpired, ProcessLookupError):
                try:
                    p.kill()
                    p.wait(timeout=2)
                except (subprocess.TimeoutExpired, ProcessLookupError):
                    pass
            logging.info("BGM 停止")


atexit.register(_stop_bgm)


# --- 拡張ポイント ---

def on_work_start():
    _start_bgm()

def on_break_detected():
    _stop_bgm()

def on_50min_reached():
    _stop_bgm()
    subprocess.run([
        "notify-send", "--urgency=normal",
        "作業50分経過", "そろそろ休憩しましょう！",
    ])
    try:
        subprocess.run([
            "canberra-gtk-play",
            "-f", "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga",
        ], check=False)
    except FileNotFoundError:
        logging.warning("効果音を再生できません: canberra-gtk-play が見つかりません")


# --- 物理デバイス監視によるアイドル検知 ---

_last_input_time = time.monotonic()
_input_lock = threading.Lock()


def _physical_devices():
    """キーボード・マウス相当の物理デバイスのパスを返す。
    仮想デバイス（Phys が空）とオーディオ SW デバイス（EV_KEY/EV_REL なし）を除外する。
    """
    EV_KEY = 1 << 1
    EV_REL = 1 << 2

    devices = []
    current_phys = None
    current_handlers = []
    current_ev = 0
    for line in open("/proc/bus/input/devices"):
        line = line.strip()
        if line.startswith("P:"):
            current_phys = line.split("=", 1)[1].strip()
        elif line.startswith("H:"):
            current_handlers = line.split("=", 1)[1].split()
        elif line.startswith("B:") and "EV=" in line:
            current_ev = int(line.split("=")[1], 16)
        elif line == "":
            if current_phys and (current_ev & (EV_KEY | EV_REL)):
                for h in current_handlers:
                    if h.startswith("event"):
                        devices.append(f"/dev/input/{h}")
            current_phys = None
            current_handlers = []
            current_ev = 0
    return devices


def _watch_device(path: str):
    global _last_input_time
    try:
        dev = evdev.InputDevice(path)
        logging.info(f"監視開始: {dev.name} ({path})")
        for event in dev.read_loop():
            if event.type != evdev.ecodes.EV_SYN:
                with _input_lock:
                    _last_input_time = time.monotonic()
    except PermissionError:
        logging.warning(f"アクセス拒否: {path} — input グループに追加されているか確認してください")
    except Exception as e:
        logging.warning(f"デバイス監視エラー ({path}): {e}")


def start_input_watchers():
    for path in _physical_devices():
        t = threading.Thread(target=_watch_device, args=(path,), daemon=True)
        t.start()


def get_idle_ms() -> int:
    with _input_lock:
        return int((time.monotonic() - _last_input_time) * 1000)


# --- メインクラス ---

class PomoWatcher:
    def __init__(self):
        self.active_seconds = 0
        self.paused = False
        self.was_on_break = True
        self.awaiting_break = False  # 50分到達後、10分アイドルになるまで True
        self.window_start = None  # 現在のウィンドウの開始時刻（monotonic）

        self.indicator = self._build_indicator()

        GLib.timeout_add(500, self._tick_once)  # 起動0.5秒後に1回だけ実行
        GLib.timeout_add_seconds(CHECK_INTERVAL_SEC, self._tick)
        GLib.timeout_add_seconds(1, self._refresh_indicator)
        logging.info("pomowatcher 開始")

    # --- トレイアイコン ---

    def _build_indicator(self):
        icon_name = _ensure_blank_icon()
        indicator = AppIndicator3.Indicator.new(
            "pomowatcher",
            icon_name,
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        indicator.set_icon_theme_path(BLANK_ICON_DIR)
        indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        indicator.set_label(f"○ {WORK_THRESHOLD_SEC // 60}:00", f"○ {WORK_THRESHOLD_SEC // 60}:00")

        menu = Gtk.Menu()

        reset_item = Gtk.MenuItem(label="リセット")
        reset_item.connect("activate", self._on_reset)
        menu.append(reset_item)

        self.pause_menu_item = Gtk.MenuItem(label="停止")
        self.pause_menu_item.connect("activate", self._on_pause_toggle)
        menu.append(self.pause_menu_item)

        quit_item = Gtk.MenuItem(label="終了")
        quit_item.connect("activate", self._on_quit)
        menu.append(quit_item)

        menu.show_all()
        indicator.set_menu(menu)
        return indicator

    def _on_quit(self, *_):
        _stop_bgm()
        Gtk.main_quit()

    def _progress_icon(self) -> str:
        icons = ["○", "◔", "◑", "◕", "●"]
        ratio = min(1.0, self.active_seconds / WORK_THRESHOLD_SEC)
        return icons[int(ratio * (len(icons) - 1))]

    def _update_indicator(self):
        if self.paused:
            self.indicator.set_label("❚❚ Paused", "❚❚ Paused")
            return
        if self.awaiting_break:
            self.indicator.set_label("Take a break!!", "Take a break!!")
            return
        elapsed = self._display_elapsed()
        remaining = max(0, WORK_THRESHOLD_SEC - elapsed)
        mins, secs = divmod(int(remaining), 60)
        label = f"{self._progress_icon()} {mins:02d}:{secs:02d}"
        self.indicator.set_label(label, label)

    # --- タイマー ---

    def _refresh_indicator(self) -> bool:
        if (
            self.was_on_break
            and not self.paused
            and not self.awaiting_break
            and get_idle_ms() <= ACTIVE_LIMIT_MS
        ):
            logging.info("作業再開を検知（即時）")
            on_work_start()
            self.was_on_break = False
            self.window_start = time.monotonic()
        self._update_indicator()
        return True

    def _display_elapsed(self) -> float:
        """コミット済み時間 + 現ウィンドウの経過秒を合計した表示用の経過時間"""
        elapsed = self.active_seconds
        if self.window_start is not None and not self.paused and not self.was_on_break:
            elapsed += min(time.monotonic() - self.window_start, CHECK_INTERVAL_SEC)
        return elapsed

    # --- メニューハンドラ ---

    def _on_reset(self, *_):
        self.active_seconds = 0
        self.window_start = time.monotonic()
        self.was_on_break = False
        self.awaiting_break = False
        self.pause_menu_item.set_label("停止")
        self._update_indicator()
        _start_bgm()  # リセット後は作業開始扱い
        logging.info("リセット")

    def _on_pause_toggle(self, *_):
        self.paused = not self.paused
        self.pause_menu_item.set_label("再開" if self.paused else "停止")
        if self.paused:
            _stop_bgm()
        else:
            # 再開時：休憩中でなければ BGM 再開
            if not self.awaiting_break and not self.was_on_break:
                _start_bgm()
        logging.info("一時停止" if self.paused else "再開")
        self._update_indicator()

    # --- 定期チェック ---

    def _tick(self) -> bool:
        if self.paused:
            return True

        idle_ms = get_idle_ms()
        is_idle = idle_ms > ACTIVE_LIMIT_MS
        idle_sec = idle_ms // 1000
        logging.info(f"idle_ms={idle_ms}, is_idle={is_idle}")

        if self.awaiting_break:
            if idle_sec >= IDLE_THRESHOLD_SEC:
                logging.info(f"休憩完了（{idle_sec // 60}分{idle_sec % 60}秒アイドル）")
                on_break_detected()
                self.active_seconds = 0
                self.was_on_break = True
                self.awaiting_break = False
            self._update_indicator()
            return True

        if not is_idle:
            if self.was_on_break:
                logging.info("作業再開を検知")
                on_work_start()
                self.was_on_break = False

            self.active_seconds += CHECK_INTERVAL_SEC
            self.window_start = time.monotonic()
            logging.info(f"作業中 ... {self.active_seconds // 60}分{self.active_seconds % 60}秒経過")

            if self.active_seconds >= WORK_THRESHOLD_SEC:
                logging.info("50分到達！通知送信")
                on_50min_reached()
                self.awaiting_break = True

        else:
            if idle_sec >= IDLE_THRESHOLD_SEC and not self.was_on_break:
                logging.info(f"休憩検知（{idle_sec // 60}分{idle_sec % 60}秒アイドル）→ リセット")
                on_break_detected()
                self.active_seconds = 0
                self.was_on_break = True

        self._update_indicator()

        return True

    def _tick_once(self) -> bool:
        self._tick()
        return False  # 繰り返さない

    def run(self):
        Gtk.main()


if __name__ == "__main__":
    start_input_watchers()
    app = PomoWatcher()
    app.run()
