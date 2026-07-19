"""LinuxのAppIndicatorトレイ表示。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import Gtk, AyatanaAppIndicator3 as AppIndicator3

from ..settings import AppSettings
from ..timer import TimerSnapshot


BLANK_ICON_NAME = "pomowatcher-blank"
BLANK_ICON_DIR = Path.home() / ".cache" / "pomowatcher"
BLANK_ICON_PATH = BLANK_ICON_DIR / f"{BLANK_ICON_NAME}.svg"


def _ensure_blank_icon() -> str:
    BLANK_ICON_DIR.mkdir(parents=True, exist_ok=True)
    if not BLANK_ICON_PATH.exists():
        BLANK_ICON_PATH.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>\n',
            encoding="utf-8",
        )
    return BLANK_ICON_NAME


class LinuxTray:
    def __init__(
        self,
        *,
        settings: AppSettings,
        on_reset: Callable[[], None],
        on_pause: Callable[[], None],
        on_restart: Callable[[], None],
        on_mute: Callable[[bool], None],
        on_volume_up: Callable[[], None],
        on_volume_down: Callable[[], None],
        on_next_track: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        icon_name = _ensure_blank_icon()
        self.indicator = AppIndicator3.Indicator.new(
            "pomowatcher",
            icon_name,
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self.indicator.set_icon_theme_path(os.fspath(BLANK_ICON_DIR))
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self.indicator.set_label("○ 50:00", "○ 50:00")

        menu = Gtk.Menu()
        pomodoro_item = Gtk.MenuItem(label="Pomodoro")
        pomodoro_menu = Gtk.Menu()
        pomodoro_item.set_submenu(pomodoro_menu)
        menu.append(pomodoro_item)

        reset_item = Gtk.MenuItem(label="リセット")
        reset_item.connect("activate", lambda *_: on_reset())
        pomodoro_menu.append(reset_item)
        self.pause_item = Gtk.MenuItem(label="停止")
        self.pause_item.connect("activate", lambda *_: on_pause())
        pomodoro_menu.append(self.pause_item)
        restart_item = Gtk.MenuItem(label="再起動")
        restart_item.connect("activate", lambda *_: on_restart())
        pomodoro_menu.append(restart_item)

        bgm_item = Gtk.MenuItem(label="BGM")
        bgm_menu = Gtk.Menu()
        bgm_item.set_submenu(bgm_menu)
        menu.append(bgm_item)
        self.mute_item = Gtk.CheckMenuItem(label="ミュート")
        self.mute_item.set_active(settings.bgm_muted)
        self.mute_item.connect("toggled", lambda item: on_mute(item.get_active()))
        bgm_menu.append(self.mute_item)
        bgm_menu.append(Gtk.SeparatorMenuItem())
        self.volume_item = Gtk.MenuItem(label=f"音量: {settings.bgm_volume}%")
        self.volume_item.set_sensitive(False)
        bgm_menu.append(self.volume_item)
        volume_up_item = Gtk.MenuItem(label="音量を上げる")
        volume_up_item.connect("activate", lambda *_: on_volume_up())
        bgm_menu.append(volume_up_item)
        volume_down_item = Gtk.MenuItem(label="音量を下げる")
        volume_down_item.connect("activate", lambda *_: on_volume_down())
        bgm_menu.append(volume_down_item)
        bgm_menu.append(Gtk.SeparatorMenuItem())
        next_item = Gtk.MenuItem(label="次の曲")
        next_item.connect("activate", lambda *_: on_next_track())
        bgm_menu.append(next_item)

        quit_item = Gtk.MenuItem(label="終了")
        quit_item.connect("activate", lambda *_: on_quit())
        menu.append(quit_item)
        menu.show_all()
        self.indicator.set_menu(menu)

    def refresh(self, snapshot: TimerSnapshot, settings: AppSettings) -> None:
        self.indicator.set_label(snapshot.label, snapshot.label)
        self.pause_item.set_label("再開" if snapshot.state.value == "paused" else "停止")
        if self.mute_item.get_active() != settings.bgm_muted:
            self.mute_item.set_active(settings.bgm_muted)
        self.volume_item.set_label(f"音量: {settings.bgm_volume}%")
