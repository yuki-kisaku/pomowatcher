"""PomowatcherのWindows 11用常駐アプリ。"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk

if sys.platform != "win32":
    raise SystemExit("このファイルはWindows 11専用です")

from ..app import PomowatcherController
from ..bgm import MpvBgmPlayer
from ..settings import AppSettings, SettingsStore
from ..timer import PomodoroTimer, TimerState
from .bgm import WindowsMpvAdapter
from .idle import configure_dpi_awareness, get_idle_ms
from .media_monitor import WindowsMediaMonitor
from .notification import WindowsNotifier
from .tray import WindowsTrayIcon, render_tray_icon


WORK_THRESHOLD_SEC = 50 * 60
IDLE_THRESHOLD_SEC = 10 * 60
ACTIVE_LIMIT_MS = 30 * 1000
POLL_INTERVAL_MS = 500

APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "pomowatcher"
SETTINGS_PATH = APP_DIR / "settings.json"
LOG_PATH = APP_DIR / "pomowatcher.log"
BGM_DIR = Path.home() / "Music" / "pomodoro-bgm"
BGM_FILE_CANDIDATES = tuple(
    BGM_DIR.with_suffix(ext) for ext in (".mp3", ".ogg", ".flac", ".m4a", ".opus", ".webm")
)


def setup_logging() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        LOG_PATH,
        maxBytes=1_000_000,
        backupCount=2,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


class SingleInstance:
    """同じWindowsユーザー内で二重起動を防ぐ。"""

    ERROR_ALREADY_EXISTS = 183

    def __init__(self) -> None:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = (
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        )
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        self._handle = kernel32.CreateMutexW(None, False, "Local\\PomowatcherWindows")
        if not self._handle:
            raise ctypes.WinError()
        self.already_running = kernel32.GetLastError() == self.ERROR_ALREADY_EXISTS

    def close(self) -> None:
        if self._handle:
            ctypes.windll.kernel32.CloseHandle(self._handle)
            self._handle = None


class PomowatcherWindowsApp:
    def __init__(self, instance: SingleInstance) -> None:
        self.instance = instance
        self.settings_store = SettingsStore(SETTINGS_PATH)
        settings = self.settings_store.load()
        self.timer = PomodoroTimer(
            work_threshold_sec=WORK_THRESHOLD_SEC,
            break_threshold_sec=IDLE_THRESHOLD_SEC,
            active_limit_ms=ACTIVE_LIMIT_MS,
            now=time.monotonic(),
        )
        self.bgm = MpvBgmPlayer(
            adapter=WindowsMpvAdapter(),
            bgm_dir=BGM_DIR,
            file_candidates=BGM_FILE_CANDIDATES,
            muted=settings.bgm_muted,
            volume=settings.bgm_volume,
        )
        self.notifier = WindowsNotifier()
        self.controller = PomowatcherController(
            timer=self.timer,
            bgm=self.bgm,
            settings=settings,
            save_settings=self.settings_store.save,
            notify_work_limit=self.notifier.work_limit_reached,
        )
        self.media_monitor = WindowsMediaMonitor()
        self.actions: queue.SimpleQueue[str] = queue.SimpleQueue()
        self._stopping = False
        self._last_icon_key: tuple[TimerState, int] | None = None

        self.root = tk.Tk()
        self.root.withdraw()
        self.tray_menu = self._build_tray_menu()
        self.tray = WindowsTrayIcon(
            "pomowatcher",
            render_tray_icon(TimerState.READY, 0),
            "Pomowatcher — 残り 50:00",
            on_menu_requested=self._request_tray_menu,
        )
        self.tray_thread = threading.Thread(
            target=self.tray.run,
            name="pomowatcher-tray",
            daemon=True,
        )

    @property
    def settings(self) -> AppSettings:
        return self.controller.settings

    def _queue_action(self, name: str):
        def enqueue() -> None:
            self.actions.put(name)

        return enqueue

    def _request_tray_menu(self) -> None:
        self.actions.put("show_menu")

    def _build_tray_menu(self) -> tk.Menu:
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label=self._tray_status_text(), state=tk.DISABLED)
        menu.add_separator()

        self._pomodoro_menu = tk.Menu(menu, tearoff=False)
        self._pomodoro_menu.add_command(
            label="リセット",
            command=self._queue_action("reset"),
        )
        self._pomodoro_menu.add_command(
            label="停止",
            command=self._queue_action("pause"),
        )
        self._pomodoro_menu.add_command(
            label="再起動",
            command=self._queue_action("restart"),
        )
        menu.add_cascade(label="Pomodoro", menu=self._pomodoro_menu)

        self._bgm_menu = tk.Menu(menu, tearoff=False)
        self._bgm_muted_var = tk.BooleanVar(
            master=self.root,
            value=self.settings.bgm_muted,
        )
        self._bgm_menu.add_checkbutton(
            label="ミュート",
            variable=self._bgm_muted_var,
            command=self._queue_action("mute"),
        )
        self._bgm_menu.add_command(
            label=f"音量: {self.settings.bgm_volume}%",
            state=tk.DISABLED,
        )
        self._bgm_menu.add_command(
            label="音量を上げる",
            command=self._queue_action("volume_up"),
        )
        self._bgm_menu.add_command(
            label="音量を下げる",
            command=self._queue_action("volume_down"),
        )
        self._bgm_menu.add_separator()
        self._bgm_menu.add_command(
            label="次の曲",
            command=self._queue_action("next_track"),
        )
        menu.add_cascade(label="BGM", menu=self._bgm_menu)

        menu.add_separator()
        menu.add_command(label="終了", command=self._queue_action("quit"))
        return menu

    def _tray_status_text(self) -> str:
        snapshot = self.timer.snapshot()
        if snapshot.state == TimerState.PAUSED:
            return "Pomowatcher — 停止中"
        if snapshot.state == TimerState.AWAITING_BREAK:
            return "Pomowatcher — 休憩してください"
        minutes, seconds = divmod(snapshot.remaining_seconds, 60)
        return f"Pomowatcher — 残り {minutes:02d}:{seconds:02d}"

    def _poll_timer(self) -> None:
        if self._stopping:
            return
        try:
            self.controller.set_other_media_playing(self.media_monitor.is_playing())
            self.controller.tick(idle_ms=get_idle_ms(), now=time.monotonic())
        except OSError as exc:
            logging.warning("入力状態を取得できません: %s", exc)
        self._drain_actions()
        self._refresh_view()
        self.root.after(POLL_INTERVAL_MS, self._poll_timer)

    def _refresh_view(self) -> None:
        snapshot = self.timer.snapshot()
        status_text = self._tray_status_text()
        self.tray.title = status_text
        self.tray_menu.entryconfigure(0, label=status_text)
        self._pomodoro_menu.entryconfigure(
            1,
            label="再開" if self.timer.paused else "停止",
        )
        self._bgm_muted_var.set(self.settings.bgm_muted)
        self._bgm_menu.entryconfigure(
            1,
            label=f"音量: {self.settings.bgm_volume}%",
        )
        icon_key = (snapshot.state, snapshot.progress_index)
        if icon_key != self._last_icon_key:
            self.tray.icon = render_tray_icon(*icon_key)
            self._last_icon_key = icon_key

    def _show_tray_menu(self) -> None:
        self._refresh_view()
        self.tray_menu.tk_popup(
            self.root.winfo_pointerx(),
            self.root.winfo_pointery(),
        )

    def _drain_actions(self) -> None:
        while True:
            try:
                action = self.actions.get_nowait()
            except queue.Empty:
                return
            try:
                self._handle_action(action)
            except Exception:
                logging.exception("トレイ操作に失敗しました: %s", action)

    def _handle_action(self, action: str) -> None:
        if action == "show_menu":
            self._show_tray_menu()
        elif action == "reset":
            self.controller.reset(now=time.monotonic())
        elif action == "pause":
            self.controller.toggle_pause(idle_ms=get_idle_ms(), now=time.monotonic())
        elif action == "mute":
            self.controller.toggle_mute()
        elif action == "volume_up":
            self.controller.change_volume(increase=True)
        elif action == "volume_down":
            self.controller.change_volume(increase=False)
        elif action == "next_track":
            self.controller.next_track()
        elif action == "restart":
            self._restart()
        elif action == "quit":
            self._quit()

    def _restart(self) -> None:
        logging.info("再起動")
        self._cleanup()
        launcher = Path(__file__).resolve().parents[2] / "pomowatcher_windows.py"
        subprocess.Popen(
            [sys.executable, str(launcher)],
            cwd=launcher.parent,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self.root.destroy()

    def _quit(self) -> None:
        logging.info("終了")
        self._cleanup()
        self.root.destroy()

    def _cleanup(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        self.media_monitor.stop()
        self.bgm.stop()
        try:
            self.tray.stop()
        except RuntimeError:
            pass
        self.instance.close()

    def run(self) -> None:
        self.media_monitor.start()
        self.tray_thread.start()
        self.root.after(100, self._poll_timer)
        logging.info("pomowatcher Windows版を開始")
        try:
            self.root.mainloop()
        finally:
            self._cleanup()


def main() -> int:
    configure_dpi_awareness()
    setup_logging()
    instance = SingleInstance()
    if instance.already_running:
        logging.info("すでに起動しているため終了")
        instance.close()
        return 0
    try:
        PomowatcherWindowsApp(instance).run()
    except Exception:
        logging.exception("起動に失敗しました")
        instance.close()
        return 1
    return 0
