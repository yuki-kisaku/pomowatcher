"""PomowatcherのLinux用常駐アプリ。"""

from __future__ import annotations

import logging
from pathlib import Path
import subprocess
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

from ..app import PomowatcherController
from ..bgm import MpvBgmPlayer
from ..settings import SettingsStore
from ..timer import PomodoroTimer
from .bgm import LinuxMpvAdapter
from .idle import get_idle_ms, start_input_watchers
from .media_monitor import MprisMediaMonitor
from .notification import LinuxNotifier
from .tray import LinuxTray


WORK_THRESHOLD_SEC = 50 * 60
IDLE_THRESHOLD_SEC = 10 * 60
ACTIVE_LIMIT_MS = 30 * 1000
CHECK_INTERVAL_SEC = 30
MEDIA_INTERVAL_SEC = 2

SETTINGS_PATH = Path.home() / ".config" / "pomowatcher" / "settings.json"
BGM_DIR = Path.home() / "Music" / "pomodoro-bgm"
BGM_FILE_CANDIDATES = tuple(
    BGM_DIR.with_suffix(ext) for ext in (".mp3", ".ogg", ".flac", ".m4a", ".opus", ".webm")
)


logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
)


class PomoWatcher:
    def __init__(
        self,
        *,
        work_threshold_sec: int = WORK_THRESHOLD_SEC,
        idle_threshold_sec: int = IDLE_THRESHOLD_SEC,
        check_interval_sec: int = CHECK_INTERVAL_SEC,
        active_limit_ms: int = ACTIVE_LIMIT_MS,
    ) -> None:
        self.settings_store = SettingsStore(SETTINGS_PATH)
        settings = self.settings_store.load()
        self.timer = PomodoroTimer(
            work_threshold_sec=work_threshold_sec,
            break_threshold_sec=idle_threshold_sec,
            active_limit_ms=active_limit_ms,
            now=time.monotonic(),
        )
        self.bgm = MpvBgmPlayer(
            adapter=LinuxMpvAdapter(),
            bgm_dir=BGM_DIR,
            file_candidates=BGM_FILE_CANDIDATES,
            muted=settings.bgm_muted,
            volume=settings.bgm_volume,
        )
        self.controller = PomowatcherController(
            timer=self.timer,
            bgm=self.bgm,
            settings=settings,
            save_settings=self.settings_store.save,
            notify_work_limit=LinuxNotifier().work_limit_reached,
        )
        self.media_monitor = MprisMediaMonitor(lambda: self.bgm.process_id)
        self.tray = LinuxTray(
            settings=settings,
            on_reset=self._on_reset,
            on_pause=self._on_pause,
            on_restart=self._on_restart,
            on_mute=self._on_mute,
            on_volume_up=lambda: self._on_volume(True),
            on_volume_down=lambda: self._on_volume(False),
            on_next_track=self.controller.next_track,
            on_quit=self._on_quit,
        )
        GLib.timeout_add(100, self._refresh_media_once)
        GLib.timeout_add(500, self._poll_once)
        GLib.timeout_add_seconds(check_interval_sec, self._poll)
        GLib.timeout_add_seconds(1, self._refresh_tray_timer)
        GLib.timeout_add_seconds(MEDIA_INTERVAL_SEC, self._refresh_media)
        logging.info("pomowatcher開始")

    def _poll(self) -> bool:
        self.controller.tick(idle_ms=get_idle_ms(), now=time.monotonic())
        self._refresh_tray()
        return True

    def _poll_once(self) -> bool:
        self._poll()
        return False

    def _refresh_media(self) -> bool:
        self.controller.set_other_media_playing(self.media_monitor.is_playing())
        return True

    def _refresh_media_once(self) -> bool:
        self._refresh_media()
        return False

    def _refresh_tray(self) -> None:
        self.tray.refresh(
            self.timer.snapshot(now=time.monotonic()),
            self.controller.settings,
        )

    def _refresh_tray_timer(self) -> bool:
        self._refresh_tray()
        return True

    def _on_reset(self) -> None:
        self.controller.reset(now=time.monotonic())
        self._refresh_tray()

    def _on_pause(self) -> None:
        self.controller.toggle_pause(idle_ms=get_idle_ms(), now=time.monotonic())
        self._refresh_tray()

    def _on_mute(self, muted: bool) -> None:
        if muted != self.controller.settings.bgm_muted:
            self.controller.toggle_mute()
        self._refresh_tray()

    def _on_volume(self, increase: bool) -> None:
        self.controller.change_volume(increase=increase)
        self._refresh_tray()

    @staticmethod
    def _on_restart() -> None:
        try:
            subprocess.Popen(
                [
                    "systemd-run",
                    "--user",
                    "--collect",
                    "--unit=pomowatcher-restart",
                    "systemctl",
                    "--user",
                    "restart",
                    "pomowatcher.service",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logging.info("pomowatcher再起動を要求")
        except FileNotFoundError:
            logging.warning("再起動できません: systemd-runが見つかりません")
        except OSError as exc:
            logging.warning("再起動を要求できません: %s", exc)

    def _on_quit(self) -> None:
        self.bgm.stop()
        Gtk.main_quit()

    def run(self) -> None:
        try:
            Gtk.main()
        finally:
            self.bgm.stop()


def main(
    *,
    work_threshold_sec: int = WORK_THRESHOLD_SEC,
    idle_threshold_sec: int = IDLE_THRESHOLD_SEC,
    check_interval_sec: int = CHECK_INTERVAL_SEC,
    active_limit_ms: int = ACTIVE_LIMIT_MS,
) -> int:
    start_input_watchers()
    PomoWatcher(
        work_threshold_sec=work_threshold_sec,
        idle_threshold_sec=idle_threshold_sec,
        check_interval_sec=check_interval_sec,
        active_limit_ms=active_limit_ms,
    ).run()
    return 0
