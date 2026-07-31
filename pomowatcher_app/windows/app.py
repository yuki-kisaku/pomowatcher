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
from ..activity import ActivityLog, format_duration
from ..bgm import MpvBgmPlayer
from ..settings import AppSettings, SettingsStore
from ..sync import StateCoordinator, StateStore, SyncClient
from ..timer import PomodoroTimer, TimerState
from .bgm import WindowsMpvAdapter
from .idle import configure_dpi_awareness, get_idle_ms
from .media_monitor import WindowsMediaMonitor
from .notification import WindowsNotifier
from .popup import TrayPopup
from .tray import WindowsTrayIcon, render_tray_icon


WORK_THRESHOLD_SEC = 50 * 60
IDLE_THRESHOLD_SEC = 10 * 60
ACTIVE_LIMIT_MS = 30 * 1000
POLL_INTERVAL_MS = 500

APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "pomowatcher"
SETTINGS_PATH = APP_DIR / "settings.json"
STATE_PATH = APP_DIR / "state.json"
ACTIVITY_PATH = APP_DIR / "activity.sqlite3"
DEVICE_ID_PATH = APP_DIR / "device-id"
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
        self.activity = ActivityLog(
            ACTIVITY_PATH,
            active_limit_ms=ACTIVE_LIMIT_MS,
        )
        sync_url = os.environ.get("POMOWATCHER_SYNC_URL", "").strip()
        self.state = StateCoordinator(
            timer=self.timer,
            store=StateStore(STATE_PATH),
            sync_client=SyncClient(
                sync_url,
                os.environ.get("POMOWATCHER_SYNC_TOKEN", ""),
            ) if sync_url else None,
            device_id_path=DEVICE_ID_PATH,
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
            notify_break_reminder=self.notifier.break_reminder,
        )
        self.controller.reconcile_timer_state()
        self.media_monitor = WindowsMediaMonitor()
        self.actions: queue.SimpleQueue[str] = queue.SimpleQueue()
        self._stopping = False
        self._last_icon_key: tuple[TimerState, int] | None = None

        self.root = tk.Tk()
        self.root.withdraw()
        self.tray_popup = TrayPopup(self.root, self.actions.put)
        self.tray = WindowsTrayIcon(
            "pomowatcher",
            render_tray_icon(TimerState.READY, 0),
            "Remaining 50:00",
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

    def _request_tray_menu(self) -> None:
        self.actions.put("show_menu")

    def _tray_status_text(self) -> str:
        snapshot = self.timer.snapshot()
        if snapshot.state == TimerState.PAUSED:
            return "Paused"
        if snapshot.state == TimerState.AWAITING_BREAK:
            return "Take a break!"
        minutes, seconds = divmod(snapshot.remaining_seconds, 60)
        return f"Remaining {minutes:02d}:{seconds:02d}"

    def _poll_timer(self) -> None:
        if self._stopping:
            return
        try:
            self.controller.set_other_media_playing(self.media_monitor.is_playing())
            idle_ms = get_idle_ms()
            self.controller.tick(idle_ms=idle_ms, now=time.monotonic())
            self.activity.update(
                idle_ms=idle_ms,
                paused=self.timer.paused,
                now=time.time(),
            )
            state_changed = self.state.synchronize(
                now=time.monotonic(),
                allow_push=idle_ms <= ACTIVE_LIMIT_MS,
            )
            if state_changed:
                self.controller.reconcile_timer_state()
        except OSError as exc:
            logging.warning("入力状態を取得できません: %s", exc)
        self._drain_actions()
        self._refresh_view()
        self.root.after(POLL_INTERVAL_MS, self._poll_timer)

    def _refresh_view(self) -> None:
        snapshot = self.timer.snapshot()
        status_text = self._tray_status_text()
        self.tray.title = status_text
        self.tray_popup.refresh(
            status_text=status_text,
            today_text=f"Today {format_duration(self.activity.today_seconds())}",
            paused=self.timer.paused,
            bgm_muted=self.settings.bgm_muted,
            bgm_volume=self.settings.bgm_volume,
        )
        icon_key = (snapshot.state, snapshot.progress_index)
        if icon_key != self._last_icon_key:
            self.tray.icon = render_tray_icon(*icon_key)
            self._last_icon_key = icon_key

    def _toggle_tray_popup(self) -> None:
        self._refresh_view()
        self.tray_popup.toggle()

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
            self._toggle_tray_popup()
        elif action == "reset":
            self.controller.reset(now=time.monotonic())
            self.activity.update(
                idle_ms=get_idle_ms(),
                paused=self.timer.paused,
                now=time.time(),
            )
        elif action == "pause":
            idle_ms = get_idle_ms()
            self.controller.toggle_pause(idle_ms=idle_ms, now=time.monotonic())
            self.activity.update(
                idle_ms=idle_ms,
                paused=self.timer.paused,
                now=time.time(),
            )
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
        if action not in {"show_menu", "restart", "quit"}:
            self.state.synchronize(now=time.monotonic(), force_push=True)

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
        self.tray_popup.hide()
        self.media_monitor.stop()
        self.bgm.stop()
        self.activity.close()
        self.state.save_local()
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
