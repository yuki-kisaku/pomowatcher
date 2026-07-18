"""Pomowatcher の Windows 11 用常駐アプリ。"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import winreg

if sys.platform != "win32":
    raise SystemExit("このファイルは Windows 11 専用です")

import pystray
from PIL import Image, ImageDraw
from windows_toasts import AudioSource, Toast, ToastAudio, WindowsToaster

from pomowatcher_core import PomodoroTimer, TimerEvent, TimerState


WORK_THRESHOLD_SEC = 50 * 60
IDLE_THRESHOLD_SEC = 10 * 60
ACTIVE_LIMIT_MS = 30 * 1000
POLL_INTERVAL_MS = 500

BGM_VOLUME_DEFAULT = 50
BGM_VOLUME_MIN = 0
BGM_VOLUME_MAX = 125
BGM_VOLUME_STEP = 10
AUDIO_EXTENSIONS = {".mp3", ".ogg", ".flac", ".m4a", ".opus", ".webm", ".wav", ".aac"}

APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "pomowatcher"
SETTINGS_PATH = APP_DIR / "settings.json"
LOG_PATH = APP_DIR / "pomowatcher.log"
BGM_DIR = Path.home() / "Music" / "pomodoro-bgm"
BGM_FILE_CANDIDATES = tuple(BGM_DIR.with_suffix(ext) for ext in (".mp3", ".ogg", ".flac", ".m4a", ".opus", ".webm"))


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def _configure_dpi_awareness() -> None:
    """高DPI画面でもトレイアイコンを正しく扱えるようにする。"""

    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        pass


def get_idle_ms() -> int:
    """現在のWindowsセッションで最後に入力されてからの時間を返す。"""

    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        raise ctypes.WinError()

    ctypes.windll.kernel32.GetTickCount.restype = ctypes.c_uint
    current = ctypes.windll.kernel32.GetTickCount()
    return ctypes.c_uint(current - info.dwTime).value


def _setup_logging() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


def _normalize_volume(value: object) -> int:
    try:
        volume = int(value)
    except (TypeError, ValueError):
        return BGM_VOLUME_DEFAULT
    if not BGM_VOLUME_MIN <= volume <= BGM_VOLUME_MAX:
        return BGM_VOLUME_DEFAULT
    return volume


def _load_settings() -> dict[str, object]:
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    except (OSError, json.JSONDecodeError) as exc:
        logging.warning("設定を読み込めません。初期値で続行します: %s", exc)
        data = {}

    return {
        "bgm_muted": data.get("bgm_muted") is True,
        "bgm_volume": _normalize_volume(data.get("bgm_volume")),
    }


def _save_settings(settings: dict[str, object]) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    temporary_path = SETTINGS_PATH.with_suffix(".tmp")
    payload = {
        "bgm_muted": settings.get("bgm_muted") is True,
        "bgm_volume": _normalize_volume(settings.get("bgm_volume")),
    }
    try:
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(SETTINGS_PATH)
    except OSError as exc:
        logging.warning("設定を保存できません: %s", exc)


class SingleInstance:
    """同じWindowsユーザー内で二重起動を防ぐ。"""

    ERROR_ALREADY_EXISTS = 183

    def __init__(self) -> None:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        self._handle = kernel32.CreateMutexW(None, False, "Local\\PomowatcherWindows")
        if not self._handle:
            raise ctypes.WinError()
        self.already_running = ctypes.windll.kernel32.GetLastError() == self.ERROR_ALREADY_EXISTS

    def close(self) -> None:
        if self._handle:
            ctypes.windll.kernel32.CloseHandle(self._handle)
            self._handle = None


class MpvBgmPlayer:
    """mpvの起動と名前付きパイプ経由の操作をまとめる。"""

    def __init__(self, *, muted: bool, volume: int) -> None:
        self.muted = muted
        self.volume = _normalize_volume(volume)
        self.process: subprocess.Popen[bytes] | None = None
        self.paused_reasons: set[str] = set()
        self.pipe_path = rf"\\.\pipe\pomowatcher-mpv-{os.getpid()}"

    def _find_target(self) -> tuple[str, Path] | None:
        if BGM_DIR.is_dir():
            files = sorted(path for path in BGM_DIR.iterdir() if path.suffix.lower() in AUDIO_EXTENSIONS)
            if files:
                return ("dir", BGM_DIR)
        for path in BGM_FILE_CANDIDATES:
            if path.is_file():
                return ("file", path)
        return None

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    @staticmethod
    def _find_mpv_executable() -> str | None:
        command = shutil.which("mpv")
        if command is not None:
            return command

        registry_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\mpv.exe"
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(root, registry_path) as key:
                    value, _ = winreg.QueryValueEx(key, None)
            except OSError:
                continue
            if value and Path(value).is_file():
                return str(value)

        candidates = (
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "mpv" / "mpv.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "mpv" / "mpv.exe",
        )
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        return None

    def start(self) -> bool:
        if self.muted or self.paused_reasons or self.is_running():
            return False

        target = self._find_target()
        if target is None:
            logging.debug("BGMが見つかりません: %s", BGM_DIR)
            return False

        mpv_path = self._find_mpv_executable()
        if mpv_path is None:
            logging.warning("mpvが見つかりません。install.ps1を再実行してください")
            return False

        kind, path = target
        command = [
            mpv_path,
            "--no-video",
            "--really-quiet",
            f"--volume={self.volume}",
            f"--input-ipc-server={self.pipe_path}",
        ]
        if kind == "dir":
            command.extend(["--shuffle", "--loop-playlist=inf"])
        else:
            command.append("--loop-file=inf")
        command.append(str(path))

        try:
            self.process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except OSError as exc:
            logging.warning("BGMを開始できません: %s", exc)
            self.process = None
            return False

        logging.info("BGM再生開始: %s (%s)", path, kind)
        return True

    def _send(self, command: list[object]) -> bool:
        if not self.is_running():
            return False
        payload = json.dumps({"command": command}, ensure_ascii=False).encode("utf-8") + b"\n"
        last_error: OSError | None = None
        for _ in range(10):
            try:
                with open(self.pipe_path, "r+b", buffering=0) as pipe:
                    pipe.write(payload)
                return True
            except OSError as exc:
                last_error = exc
                time.sleep(0.05)
        logging.warning("mpv操作に失敗しました: %s", last_error)
        return False

    def pause(self, reason: str) -> bool:
        if reason in self.paused_reasons or not self.is_running():
            return False
        if not self.paused_reasons and not self._send(["set_property", "pause", True]):
            return False
        self.paused_reasons.add(reason)
        logging.info("BGM一時停止（%s）", reason)
        return True

    def release(self, reason: str) -> bool:
        if reason not in self.paused_reasons:
            return False
        self.paused_reasons.remove(reason)
        if self.paused_reasons or self.muted or not self.is_running():
            return False
        if not self._send(["set_property", "pause", False]):
            return False
        logging.info("BGM再開")
        return True

    def set_muted(self, muted: bool) -> None:
        self.muted = muted
        if muted:
            self.pause("mute")
        else:
            self.release("mute")

    def set_volume(self, volume: int) -> int:
        self.volume = _normalize_volume(volume)
        if self.is_running():
            self._send(["set_property", "volume", self.volume])
        logging.info("BGM音量 %s%%", self.volume)
        return self.volume

    def next_track(self) -> bool:
        if self.muted or not self.is_running():
            return False
        if not self._send(["playlist-next", "weak"]):
            return False
        logging.info("BGM次の曲")
        return True

    def stop(self) -> None:
        process = self.process
        self.process = None
        self.paused_reasons.clear()
        if process is None:
            return
        try:
            process.terminate()
            process.wait(timeout=2)
        except (subprocess.TimeoutExpired, ProcessLookupError):
            try:
                process.kill()
                process.wait(timeout=2)
            except (subprocess.TimeoutExpired, ProcessLookupError):
                pass
        logging.info("BGM停止")


class WindowsNotifier:
    def __init__(self) -> None:
        self._toaster = WindowsToaster("Pomowatcher")

    def work_limit_reached(self) -> None:
        toast = Toast()
        toast.text_fields = ["作業50分経過", "そろそろ休憩しましょう！"]
        toast.audio = ToastAudio(AudioSource.Reminder)
        try:
            self._toaster.show_toast(toast)
        except Exception as exc:
            logging.warning("通知を表示できません: %s", exc)


class PomowatcherWindowsApp:
    def __init__(self, instance: SingleInstance) -> None:
        self.instance = instance
        self.settings = _load_settings()
        self.timer = PomodoroTimer(
            work_threshold_sec=WORK_THRESHOLD_SEC,
            break_threshold_sec=IDLE_THRESHOLD_SEC,
            active_limit_ms=ACTIVE_LIMIT_MS,
            now=time.monotonic(),
        )
        self.bgm = MpvBgmPlayer(
            muted=self.settings["bgm_muted"] is True,
            volume=_normalize_volume(self.settings["bgm_volume"]),
        )
        self.notifier = WindowsNotifier()
        self.actions: queue.SimpleQueue[str] = queue.SimpleQueue()
        self._stopping = False
        self._last_icon_key: tuple[TimerState, int] | None = None

        self.root = tk.Tk()
        self.root.withdraw()

        self.tray = pystray.Icon(
            "pomowatcher",
            self._render_tray_icon(TimerState.READY, 0),
            "Pomowatcher — 残り 50:00",
            self._build_tray_menu(),
        )
        self.tray_thread = threading.Thread(target=self.tray.run, name="pomowatcher-tray", daemon=True)

    def _queue_action(self, name: str):
        def enqueue(_icon: pystray.Icon, _item: pystray.MenuItem) -> None:
            self.actions.put(name)

        return enqueue

    @staticmethod
    def _noop(_icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        return None

    def _build_tray_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem(lambda _item: self._tray_status_text(), self._noop, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Pomodoro",
                pystray.Menu(
                    pystray.MenuItem("リセット", self._queue_action("reset")),
                    pystray.MenuItem(
                        lambda _item: "再開" if self.timer.paused else "停止",
                        self._queue_action("pause"),
                    ),
                    pystray.MenuItem("再起動", self._queue_action("restart")),
                ),
            ),
            pystray.MenuItem(
                "BGM",
                pystray.Menu(
                    pystray.MenuItem(
                        "ミュート",
                        self._queue_action("mute"),
                        checked=lambda _item: self.settings["bgm_muted"] is True,
                    ),
                    pystray.MenuItem(
                        lambda _item: f"音量: {self.settings['bgm_volume']}%",
                        self._noop,
                        enabled=False,
                    ),
                    pystray.MenuItem("音量を上げる", self._queue_action("volume_up")),
                    pystray.MenuItem("音量を下げる", self._queue_action("volume_down")),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem("次の曲", self._queue_action("next_track")),
                ),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("終了", self._queue_action("quit")),
        )

    def _tray_status_text(self) -> str:
        snapshot = self.timer.snapshot()
        if snapshot.state == TimerState.PAUSED:
            return "Pomowatcher — 停止中"
        if snapshot.state == TimerState.AWAITING_BREAK:
            return "Pomowatcher — 休憩してください"
        return f"Pomowatcher — 残り {snapshot.remaining_seconds // 60:02d}:{snapshot.remaining_seconds % 60:02d}"

    @staticmethod
    def _render_tray_icon(state: TimerState, progress_index: int) -> Image.Image:
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        box = (10, 10, 54, 54)
        draw.ellipse(box, outline=(135, 145, 160, 255), width=7)

        if state == TimerState.PAUSED:
            draw.rectangle((22, 20, 27, 44), fill=(185, 190, 200, 255))
            draw.rectangle((37, 20, 42, 44), fill=(185, 190, 200, 255))
        elif state == TimerState.AWAITING_BREAK:
            draw.ellipse(box, fill=(230, 126, 34, 255))
            draw.rectangle((30, 20, 34, 36), fill=(255, 255, 255, 255))
            draw.ellipse((30, 41, 34, 45), fill=(255, 255, 255, 255))
        elif progress_index > 0:
            end = -90 + 90 * progress_index
            draw.arc(box, start=-90, end=end, fill=(62, 156, 255, 255), width=7)
        return image

    def _handle_timer_events(self, events: tuple[TimerEvent, ...]) -> None:
        for event in events:
            if event == TimerEvent.WORK_STARTED:
                logging.info("作業開始を検知")
                self.bgm.release("app")
                self.bgm.release("idle")
                self.bgm.start()
            elif event == TimerEvent.ACTIVITY_RESUMED:
                logging.info("作業再開を検知")
                if not self.bgm.release("idle"):
                    self.bgm.start()
            elif event == TimerEvent.IDLE_STARTED:
                logging.info("アイドル開始")
                self.bgm.pause("idle")
            elif event == TimerEvent.BREAK_DETECTED:
                logging.info("10分の休憩を検知してリセット")
                self.bgm.stop()
            elif event == TimerEvent.WORK_LIMIT_REACHED:
                logging.info("50分到達")
                self.bgm.stop()
                self.notifier.work_limit_reached()

    def _poll_timer(self) -> None:
        if self._stopping:
            return
        try:
            idle_ms = get_idle_ms()
            events = self.timer.update(idle_ms=idle_ms, now=time.monotonic())
            self._handle_timer_events(events)
        except OSError as exc:
            logging.warning("入力状態を取得できません: %s", exc)
        self._drain_actions()
        self._refresh_view()
        self.root.after(POLL_INTERVAL_MS, self._poll_timer)

    def _refresh_view(self) -> None:
        snapshot = self.timer.snapshot()
        self.tray.title = self._tray_status_text()
        icon_key = (snapshot.state, snapshot.progress_index)
        if icon_key != self._last_icon_key:
            self.tray.icon = self._render_tray_icon(*icon_key)
            self._last_icon_key = icon_key
        try:
            self.tray.update_menu()
        except (AttributeError, RuntimeError):
            pass

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
        if action == "reset":
            events = self.timer.reset(now=time.monotonic())
            self._handle_timer_events(events)
            logging.info("リセット")
        elif action == "pause":
            paused = not self.timer.paused
            self.timer.set_paused(paused, now=time.monotonic())
            if paused:
                self.bgm.pause("app")
            else:
                idle_ms = get_idle_ms()
                if idle_ms > ACTIVE_LIMIT_MS:
                    self.bgm.pause("idle")
                self.bgm.release("app")
                if not self.timer.was_on_break and not self.timer.awaiting_break and idle_ms <= ACTIVE_LIMIT_MS:
                    if not self.bgm.release("idle"):
                        self.bgm.start()
            logging.info("一時停止" if paused else "再開")
        elif action == "mute":
            muted = not (self.settings["bgm_muted"] is True)
            self.settings["bgm_muted"] = muted
            self.bgm.set_muted(muted)
            _save_settings(self.settings)
            if not muted and self.timer.snapshot().state == TimerState.WORKING:
                self.bgm.start()
        elif action in {"volume_up", "volume_down"}:
            delta = BGM_VOLUME_STEP if action == "volume_up" else -BGM_VOLUME_STEP
            current = _normalize_volume(self.settings["bgm_volume"])
            volume = max(BGM_VOLUME_MIN, min(BGM_VOLUME_MAX, current + delta))
            self.settings["bgm_volume"] = self.bgm.set_volume(volume)
            _save_settings(self.settings)
        elif action == "next_track":
            if not self.bgm.next_track() and self.timer.snapshot().state == TimerState.WORKING:
                self.bgm.start()
        elif action == "restart":
            self._restart()
        elif action == "quit":
            self._quit()

    def _restart(self) -> None:
        logging.info("再起動")
        self._cleanup()
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve())],
            cwd=Path(__file__).resolve().parent,
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
        self.bgm.stop()
        try:
            self.tray.stop()
        except RuntimeError:
            pass
        self.instance.close()

    def run(self) -> None:
        self.tray_thread.start()
        self.root.after(100, self._poll_timer)
        logging.info("pomowatcher Windows版を開始")
        try:
            self.root.mainloop()
        finally:
            self._cleanup()


def main() -> int:
    _configure_dpi_awareness()
    _setup_logging()
    instance = SingleInstance()
    if instance.already_running:
        logging.info("すでに起動しているため終了")
        instance.close()
        return 0

    try:
        app = PomowatcherWindowsApp(instance)
        app.run()
    except Exception:
        logging.exception("起動に失敗しました")
        instance.close()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
