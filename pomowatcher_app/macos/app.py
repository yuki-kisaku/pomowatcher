"""Ubuntu版の操作感を再現するmacOSメニューバーアプリ。"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import subprocess
import sys
import time

if sys.platform != "darwin":
    raise SystemExit("このファイルはmacOS専用です")

import rumps

from ..app import PomowatcherController
from ..activity import ActivityLog, format_duration
from ..bgm import MpvBgmPlayer
from ..settings import SettingsStore
from ..sync import StateCoordinator, StateStore, SyncClient
from ..timer import PomodoroTimer, TimerState
from .bgm import MacMpvAdapter
from .idle import get_idle_ms
from .notification import MacNotifier


WORK_THRESHOLD_SEC = 50 * 60
IDLE_THRESHOLD_SEC = 10 * 60
ACTIVE_LIMIT_MS = 30 * 1000
APP_DIR = Path.home() / "Library" / "Application Support" / "Pomowatcher"
SETTINGS_PATH = APP_DIR / "settings.json"
STATE_PATH = APP_DIR / "state.json"
ACTIVITY_PATH = APP_DIR / "activity.sqlite3"
DEVICE_ID_PATH = APP_DIR / "device-id"
BGM_DIR = Path.home() / "Music" / "pomodoro-bgm"
BGM_FILE_CANDIDATES = tuple(
    BGM_DIR.with_suffix(ext) for ext in (".mp3", ".ogg", ".flac", ".m4a", ".opus", ".webm")
)


class PomowatcherMacApp(rumps.App):
    def __init__(self) -> None:
        super().__init__("Pomowatcher", title="○ 50:00", quit_button=None)
        store = SettingsStore(SETTINGS_PATH)
        settings = store.load()
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
                sync_url, os.environ.get("POMOWATCHER_SYNC_TOKEN", "")
            ) if sync_url else None,
            device_id_path=DEVICE_ID_PATH,
            now=time.monotonic(),
        )
        self.controller = PomowatcherController(
            timer=self.timer,
            bgm=MpvBgmPlayer(
                adapter=MacMpvAdapter(),
                bgm_dir=BGM_DIR,
                file_candidates=BGM_FILE_CANDIDATES,
                muted=settings.bgm_muted,
                volume=settings.bgm_volume,
            ),
            settings=settings,
            save_settings=store.save,
            notify_work_limit=MacNotifier().work_limit_reached,
        )
        self.controller.reconcile_timer_state()
        self.remaining_item = rumps.MenuItem("Remaining 50:00")
        self.today_item = rumps.MenuItem("Today 0m")
        self.pause_item = rumps.MenuItem("Pause", callback=self.toggle_pause)
        self.mute_item = rumps.MenuItem("Mute", callback=self.toggle_mute)
        self.volume_item = rumps.MenuItem(f"Volume: {settings.bgm_volume}%")
        pomodoro_menu = rumps.MenuItem("Pomodoro")
        pomodoro_menu.add(rumps.MenuItem("Reset", callback=self.reset))
        pomodoro_menu.add(self.pause_item)
        pomodoro_menu.add(rumps.MenuItem("Restart", callback=self.restart))
        bgm_menu = rumps.MenuItem("BGM")
        bgm_menu.add(self.mute_item)
        bgm_menu.add(rumps.separator)
        bgm_menu.add(self.volume_item)
        bgm_menu.add(rumps.MenuItem("Volume Up", callback=lambda _: self.volume(True)))
        bgm_menu.add(rumps.MenuItem("Volume Down", callback=lambda _: self.volume(False)))
        bgm_menu.add(rumps.separator)
        bgm_menu.add(
            rumps.MenuItem("Next Track", callback=lambda _: self.controller.next_track())
        )
        self.menu = [
            self.remaining_item,
            self.today_item,
            None,
            pomodoro_menu,
            bgm_menu,
            None,
            rumps.MenuItem("Quit", callback=self.quit_app),
        ]
        self.mute_item.state = settings.bgm_muted
        self.poll = rumps.Timer(self.tick, 0.5)
        self.poll.start()

    def _refresh(self) -> None:
        snapshot = self.timer.snapshot(now=time.monotonic())
        self.title = snapshot.label
        if snapshot.state == TimerState.PAUSED:
            remaining_text = "Paused"
        elif snapshot.state == TimerState.AWAITING_BREAK:
            remaining_text = "Take a break!"
        else:
            minutes, seconds = divmod(snapshot.remaining_seconds, 60)
            remaining_text = f"Remaining {minutes:02d}:{seconds:02d}"
        self.remaining_item.title = remaining_text
        self.today_item.title = f"Today {format_duration(self.activity.today_seconds())}"
        self.pause_item.title = "Resume" if snapshot.state == TimerState.PAUSED else "Pause"
        self.mute_item.state = self.controller.settings.bgm_muted
        self.volume_item.title = f"Volume: {self.controller.settings.bgm_volume}%"

    def tick(self, _=None) -> None:
        now = time.monotonic()
        idle_ms = get_idle_ms()
        self.controller.tick(idle_ms=idle_ms, now=now)
        self.activity.update(
            idle_ms=idle_ms,
            paused=self.timer.paused,
            now=time.time(),
        )
        state_changed = self.state.synchronize(
            now=now,
            allow_push=idle_ms <= ACTIVE_LIMIT_MS,
        )
        if state_changed:
            self.controller.reconcile_timer_state()
        self._refresh()

    def reset(self, _=None) -> None:
        self.controller.reset(now=time.monotonic())
        self.activity.update(
            idle_ms=get_idle_ms(),
            paused=self.timer.paused,
            now=time.time(),
        )
        self.state.synchronize(now=time.monotonic(), force_push=True)
        self._refresh()

    def toggle_pause(self, _=None) -> None:
        idle_ms = get_idle_ms()
        self.controller.toggle_pause(idle_ms=idle_ms, now=time.monotonic())
        self.activity.update(
            idle_ms=idle_ms,
            paused=self.timer.paused,
            now=time.time(),
        )
        self.state.synchronize(now=time.monotonic(), force_push=True)
        self._refresh()

    def toggle_mute(self, _=None) -> None:
        self.controller.toggle_mute()
        self._refresh()

    def volume(self, increase: bool) -> None:
        self.controller.change_volume(increase=increase)
        self._refresh()

    def restart(self, _=None) -> None:
        subprocess.Popen([sys.executable, str(Path(sys.argv[0]).resolve())])
        self.quit_app()

    def quit_app(self, _=None) -> None:
        self.state.save_local()
        self.controller.bgm.stop()
        self.activity.close()
        rumps.quit_application()


def main() -> int:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=APP_DIR / "pomowatcher.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    PomowatcherMacApp().run()
    return 0
