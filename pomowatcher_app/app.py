"""OS共通のタイマーイベントとBGM動作ルール。"""

from __future__ import annotations

import logging
from typing import Callable, Protocol

from .settings import (
    AppSettings,
    BGM_VOLUME_MAX,
    BGM_VOLUME_MIN,
    BGM_VOLUME_STEP,
)
from .timer import PomodoroTimer, TimerEvent, TimerState


class BgmPlayer(Protocol):
    def start(self) -> bool: ...
    def pause(self, reason: str) -> bool: ...
    def release(self, reason: str) -> bool: ...
    def set_muted(self, muted: bool) -> None: ...
    def set_volume(self, volume: int) -> int: ...
    def next_track(self) -> bool: ...
    def stop(self) -> None: ...


class PomowatcherController:
    """タイマー・BGM・他メディア連動の仕様をOSから独立させる。"""

    def __init__(
        self,
        *,
        timer: PomodoroTimer,
        bgm: BgmPlayer,
        settings: AppSettings,
        save_settings: Callable[[AppSettings], None],
        notify_work_limit: Callable[[], None],
    ) -> None:
        self.timer = timer
        self.bgm = bgm
        self.settings = settings
        self.save_settings = save_settings
        self.notify_work_limit = notify_work_limit
        self.other_media_playing = False

    def tick(self, *, idle_ms: int, now: float) -> tuple[TimerEvent, ...]:
        events = self.timer.update(idle_ms=idle_ms, now=now)
        self._handle_timer_events(events)
        return events

    def _handle_timer_events(self, events: tuple[TimerEvent, ...]) -> None:
        for event in events:
            if event == TimerEvent.WORK_STARTED:
                logging.info("作業開始を検知")
                self.bgm.release("app")
                self.bgm.release("idle")
                self._start_bgm_if_working()
            elif event == TimerEvent.ACTIVITY_RESUMED:
                logging.info("作業再開を検知")
                self.bgm.release("idle")
                self._start_bgm_if_working()
            elif event == TimerEvent.IDLE_STARTED:
                logging.info("アイドル開始")
                self.bgm.pause("idle")
            elif event == TimerEvent.BREAK_DETECTED:
                logging.info("10分の休憩を検知してリセット")
                self.bgm.stop()
            elif event == TimerEvent.WORK_LIMIT_REACHED:
                logging.info("50分到達")
                self.bgm.stop()
                self.notify_work_limit()

    def set_other_media_playing(self, playing: bool) -> bool:
        if playing == self.other_media_playing:
            return False
        self.other_media_playing = playing
        if playing:
            self.bgm.pause("media")
            logging.info("他メディアの再生を検知")
        else:
            logging.info("他メディアの再生終了を検知")
            self.bgm.release("media")
            self._start_bgm_if_working()
        return True

    def reset(self, *, now: float) -> None:
        self._handle_timer_events(self.timer.reset(now=now))
        logging.info("リセット")

    def toggle_pause(self, *, idle_ms: int, now: float) -> bool:
        paused = not self.timer.paused
        self.timer.set_paused(paused, now=now)
        if paused:
            self.bgm.pause("app")
        else:
            if idle_ms > self.timer.active_limit_ms:
                self.bgm.pause("idle")
            else:
                self.bgm.release("idle")
            self.bgm.release("app")
            self._start_bgm_if_working()
        logging.info("一時停止" if paused else "再開")
        return paused

    def toggle_mute(self) -> bool:
        muted = not self.settings.bgm_muted
        self.settings.bgm_muted = muted
        self.bgm.set_muted(muted)
        self.save_settings(self.settings)
        if not muted:
            self._start_bgm_if_working()
        logging.info("BGMミュート ON" if muted else "BGMミュート OFF")
        return muted

    def change_volume(self, *, increase: bool) -> int:
        delta = BGM_VOLUME_STEP if increase else -BGM_VOLUME_STEP
        volume = max(
            BGM_VOLUME_MIN,
            min(BGM_VOLUME_MAX, self.settings.bgm_volume + delta),
        )
        self.settings.bgm_volume = self.bgm.set_volume(volume)
        self.save_settings(self.settings)
        return self.settings.bgm_volume

    def next_track(self) -> None:
        if not self.bgm.next_track():
            self._start_bgm_if_working()

    def _start_bgm_if_working(self) -> None:
        if self.timer.snapshot().state != TimerState.WORKING:
            return
        if self.other_media_playing:
            self.bgm.pause("media")
            return
        self.bgm.start()
