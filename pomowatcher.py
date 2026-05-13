#!/usr/bin/env python3
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

logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                    format="%(asctime)s %(message)s", datefmt="%H:%M:%S")


# --- 拡張ポイント ---

def on_work_start():
    pass  # 将来: BGM再生など

def on_break_detected():
    pass  # 将来: BGM停止など

def on_50min_reached():
    subprocess.run([
        "notify-send", "--urgency=normal",
        "作業50分経過", "そろそろ休憩しましょう！",
    ])


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
        self.notified_break = False  # 50分通知済みフラグ
        self.window_start = None  # 現在のウィンドウの開始時刻（monotonic）

        self.indicator = self._build_indicator()
        self.window, self.progress_bar, self.time_label, self.pause_btn = self._build_window()

        GLib.timeout_add(500, self._tick_once)  # 起動0.5秒後に1回だけ実行
        GLib.timeout_add_seconds(CHECK_INTERVAL_SEC, self._tick)
        GLib.timeout_add_seconds(1, self._refresh_window)
        logging.info("pomowatcher 開始")

    # --- トレイアイコン ---

    def _build_indicator(self):
        indicator = AppIndicator3.Indicator.new(
            "pomowatcher",
            "appointment-soon",
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        indicator.set_label(f"○ {WORK_THRESHOLD_SEC // 60}:00", f"○ {WORK_THRESHOLD_SEC // 60}:00")

        menu = Gtk.Menu()

        show_item = Gtk.MenuItem(label="開く")
        show_item.connect("activate", self._show_window)
        menu.append(show_item)

        menu.show_all()
        indicator.set_menu(menu)
        return indicator

    def _progress_icon(self) -> str:
        icons = ["○", "◔", "◑", "◕", "●"]
        ratio = min(1.0, self.active_seconds / WORK_THRESHOLD_SEC)
        return icons[int(ratio * (len(icons) - 1))]

    def _update_indicator(self):
        if self.paused:
            self.indicator.set_label("❚❚ Paused", "❚❚ Paused")
            return
        if self.notified_break:
            self.indicator.set_label("Take a break!!", "Take a break!!")
            return
        elapsed = self._display_elapsed()
        remaining = max(0, WORK_THRESHOLD_SEC - elapsed)
        mins, secs = divmod(int(remaining), 60)
        label = f"{self._progress_icon()} {mins:02d}:{secs:02d}"
        self.indicator.set_label(label, label)

    # --- ポップアップウィンドウ ---

    def _build_window(self):
        win = Gtk.Window(title="Pomodoro Watcher")
        win.set_default_size(300, 140)
        win.set_resizable(False)
        win.set_keep_above(True)
        win.connect("delete-event", lambda w, e: w.hide() or True)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        vbox.set_margin_top(16)
        vbox.set_margin_bottom(16)
        vbox.set_margin_start(20)
        vbox.set_margin_end(20)

        progress = Gtk.ProgressBar()
        progress.set_show_text(False)
        vbox.pack_start(progress, False, False, 0)

        time_lbl = Gtk.Label(label="残り 50:00")
        vbox.pack_start(time_lbl, False, False, 0)

        btn_box = Gtk.Box(spacing=8)
        btn_box.set_halign(Gtk.Align.CENTER)

        reset_btn = Gtk.Button(label="リセット")
        reset_btn.connect("clicked", self._on_reset)
        btn_box.pack_start(reset_btn, False, False, 0)

        pause_btn = Gtk.Button(label="一時停止")
        pause_btn.connect("clicked", self._on_pause_toggle)
        btn_box.pack_start(pause_btn, False, False, 0)

        vbox.pack_start(btn_box, False, False, 0)
        win.add(vbox)

        return win, progress, time_lbl, pause_btn

    def _show_window(self, *_):
        self._update_window()
        self.window.show_all()
        self.window.present()

    def _refresh_window(self) -> bool:
        self._update_indicator()
        self._update_window()
        return True

    def _display_elapsed(self) -> float:
        """コミット済み時間 + 現ウィンドウの経過秒を合計した表示用の経過時間"""
        elapsed = self.active_seconds
        if self.window_start is not None and not self.paused and not self.was_on_break:
            elapsed += min(time.monotonic() - self.window_start, CHECK_INTERVAL_SEC)
        return elapsed

    def _update_window(self):
        elapsed = self._display_elapsed()
        remaining = max(0, WORK_THRESHOLD_SEC - elapsed)
        fraction = min(1.0, elapsed / WORK_THRESHOLD_SEC)
        mins, secs = divmod(int(remaining), 60)
        self.progress_bar.set_fraction(fraction)
        self.time_label.set_text(f"残り {mins:02d}:{secs:02d}")
        self.pause_btn.set_label("再開" if self.paused else "一時停止")

    # --- ボタンハンドラ ---

    def _on_reset(self, *_):
        self.active_seconds = 0
        self.window_start = time.monotonic()
        self.was_on_break = False
        self.notified_break = False
        self._update_indicator()
        self._update_window()
        logging.info("リセット")

    def _on_pause_toggle(self, *_):
        self.paused = not self.paused
        logging.info("一時停止" if self.paused else "再開")
        self._update_indicator()
        self._update_window()

    # --- 定期チェック ---

    def _tick(self) -> bool:
        if self.paused:
            return True

        idle_ms = get_idle_ms()
        is_idle = idle_ms > ACTIVE_LIMIT_MS
        logging.info(f"idle_ms={idle_ms}, is_idle={is_idle}")

        if not is_idle:
            if self.was_on_break:
                logging.info("作業再開を検知")
                on_work_start()
                self.was_on_break = False
                self.notified_break = False

            self.active_seconds += CHECK_INTERVAL_SEC
            self.window_start = time.monotonic()
            logging.info(f"作業中 ... {self.active_seconds // 60}分{self.active_seconds % 60}秒経過")

            if self.active_seconds >= WORK_THRESHOLD_SEC:
                logging.info("50分到達！通知送信")
                on_50min_reached()
                self.active_seconds = 0
                self.was_on_break = True
                self.notified_break = True

        else:
            idle_sec = idle_ms // 1000
            if idle_sec >= IDLE_THRESHOLD_SEC and not self.was_on_break:
                logging.info(f"休憩検知（{idle_sec // 60}分{idle_sec % 60}秒アイドル）→ リセット")
                on_break_detected()
                self.active_seconds = 0
                self.was_on_break = True

        self._update_indicator()
        self._update_window()

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
