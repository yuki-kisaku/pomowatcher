"""LinuxのMPRISメディア監視。"""

from __future__ import annotations

import logging
from typing import Callable

from gi.repository import Gio, GLib


MPRIS_PREFIX = "org.mpris.MediaPlayer2."
MPRIS_PLAYER_PATH = "/org/mpris/MediaPlayer2"
MPRIS_PLAYER_INTERFACE = "org.mpris.MediaPlayer2.Player"


class MprisMediaMonitor:
    def __init__(self, bgm_process_id: Callable[[], int | None]) -> None:
        self._bgm_process_id = bgm_process_id
        self._session_bus = None
        self._warned = False

    def _get_session_bus(self):
        if self._session_bus is not None:
            return self._session_bus
        try:
            self._session_bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            return self._session_bus
        except GLib.Error as exc:
            if not self._warned:
                logging.warning("MPRISを確認できません。BGM連動なしで続行します: %s", exc)
                self._warned = True
            return None

    @staticmethod
    def _call(bus, name, path, interface, method, params, result_type):
        return bus.call_sync(
            name,
            path,
            interface,
            method,
            params,
            GLib.VariantType.new(result_type) if result_type else None,
            Gio.DBusCallFlags.NONE,
            1000,
            None,
        )

    def _is_own_bgm(self, bus, name: str) -> bool:
        bgm_pid = self._bgm_process_id()
        if bgm_pid is None:
            return False
        try:
            result = self._call(
                bus,
                "org.freedesktop.DBus",
                "/org/freedesktop/DBus",
                "org.freedesktop.DBus",
                "GetConnectionUnixProcessID",
                GLib.Variant("(s)", (name,)),
                "(u)",
            )
            return result.unpack()[0] == bgm_pid
        except GLib.Error:
            return False

    def is_playing(self) -> bool:
        bus = self._get_session_bus()
        if bus is None:
            return False
        try:
            result = self._call(
                bus,
                "org.freedesktop.DBus",
                "/org/freedesktop/DBus",
                "org.freedesktop.DBus",
                "ListNames",
                None,
                "(as)",
            )
            names = result.unpack()[0]
        except GLib.Error as exc:
            logging.warning("MPRISプレイヤー一覧を読めません: %s", exc)
            return False
        for name in names:
            if not name.startswith(MPRIS_PREFIX) or self._is_own_bgm(bus, name):
                continue
            try:
                result = self._call(
                    bus,
                    name,
                    MPRIS_PLAYER_PATH,
                    "org.freedesktop.DBus.Properties",
                    "Get",
                    GLib.Variant("(ss)", (MPRIS_PLAYER_INTERFACE, "PlaybackStatus")),
                    "(v)",
                )
                status = result.get_child_value(0).get_variant().unpack()
            except GLib.Error:
                continue
            if status == "Playing":
                return True
        return False
