"""Windowsのシステムメディアセッション監視。"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Awaitable, Callable

try:
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus,
    )
except ImportError:
    GlobalSystemMediaTransportControlsSessionManager = None
    GlobalSystemMediaTransportControlsSessionPlaybackStatus = None


ManagerFactory = Callable[[], Awaitable[object]]


async def _request_manager() -> object:
    if GlobalSystemMediaTransportControlsSessionManager is None:
        raise RuntimeError("winrt-Windows.Media.Controlがインストールされていません")
    return await GlobalSystemMediaTransportControlsSessionManager.request_async()


class WindowsMediaMonitor:
    """他アプリの音楽・動画が再生中かをバックグラウンドで監視する。"""

    def __init__(
        self,
        *,
        manager_factory: ManagerFactory = _request_manager,
        poll_interval_sec: float = 1.0,
    ) -> None:
        self._manager_factory = manager_factory
        self._poll_interval_sec = poll_interval_sec
        self._playing = False
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="pomowatcher-media-monitor",
            daemon=True,
        )
        self._thread.start()

    def is_playing(self) -> bool:
        with self._lock:
            return self._playing

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def _set_playing(self, playing: bool) -> None:
        with self._lock:
            self._playing = playing

    def _run(self) -> None:
        try:
            asyncio.run(self._poll())
        except Exception as exc:
            logging.warning("Windowsメディア監視を開始できません: %s", exc)
            self._set_playing(False)

    async def _poll(self) -> None:
        manager = await self._manager_factory()
        while not self._stop_event.is_set():
            try:
                self._set_playing(self._has_other_playing_session(manager))
            except Exception as exc:
                logging.warning("Windowsメディア状態を確認できません: %s", exc)
                self._set_playing(False)
            await asyncio.sleep(self._poll_interval_sec)

    @staticmethod
    def _has_other_playing_session(manager: object) -> bool:
        playing_status = GlobalSystemMediaTransportControlsSessionPlaybackStatus
        if playing_status is None:
            return False
        for session in manager.get_sessions():
            source = str(session.source_app_user_model_id).lower()
            if "pomowatcher" in source or "mpv" in source:
                continue
            playback_info = session.get_playback_info()
            if playback_info.playback_status == playing_status.PLAYING:
                return True
        return False
