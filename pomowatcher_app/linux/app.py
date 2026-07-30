"""PomowatcherのLinux用常駐アプリ。"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import subprocess
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

from ..app import PomowatcherController
from ..activity import ActivityLog
from ..bgm import MpvBgmPlayer
from ..settings import SettingsStore
from ..sync import StateCoordinator, StateStore, SyncClient
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
STATE_PATH = Path.home() / ".local" / "state" / "pomowatcher" / "state.json"
ACTIVITY_PATH = Path.home() / ".local" / "state" / "pomowatcher" / "activity.sqlite3"
DEVICE_ID_PATH = Path.home() / ".config" / "pomowatcher" / "device-id"
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
        self.activity = ActivityLog(
            ACTIVITY_PATH,
            active_limit_ms=active_limit_ms,
            gap_limit_sec=check_interval_sec * 3,
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
        self.controller.reconcile_timer_state()
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
        idle_ms = get_idle_ms()
        self.controller.tick(idle_ms=idle_ms, now=time.monotonic())
        self.activity.update(
            idle_ms=idle_ms,
            paused=self.timer.paused,
            now=time.time(),
        )
        state_changed = self.state.synchronize(
            now=time.monotonic(),
            allow_push=idle_ms <= self.timer.active_limit_ms,
        )
        if state_changed:
            self.controller.reconcile_timer_state()
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
            self.activity.today_seconds(),
        )

    def _refresh_tray_timer(self) -> bool:
        self._refresh_tray()
        return True

    def _on_reset(self) -> None:
        self.controller.reset(now=time.monotonic())
        self.activity.update(
            idle_ms=get_idle_ms(),
            paused=self.timer.paused,
            now=time.time(),
        )
        self.state.synchronize(now=time.monotonic(), force_push=True)
        self._refresh_tray()

    def _on_pause(self) -> None:
        idle_ms = get_idle_ms()
        self.controller.toggle_pause(idle_ms=idle_ms, now=time.monotonic())
        self.activity.update(
            idle_ms=idle_ms,
            paused=self.timer.paused,
            now=time.time(),
        )
        self.state.synchronize(now=time.monotonic(), force_push=True)
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
        self.state.save_local()
        self.bgm.stop()
        Gtk.main_quit()

    def run(self) -> None:
        try:
            Gtk.main()
        finally:
            self.bgm.stop()
            self.activity.close()


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
