"""OSに依存しないPomodoroタイマーの状態管理。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any


class TimerEvent(str, Enum):
    """タイマー更新によって発生する、外部処理が必要な出来事。"""

    WORK_STARTED = "work_started"
    ACTIVITY_RESUMED = "activity_resumed"
    IDLE_STARTED = "idle_started"
    BREAK_DETECTED = "break_detected"
    WORK_LIMIT_REACHED = "work_limit_reached"


class TimerState(str, Enum):
    READY = "ready"
    WORKING = "working"
    IDLE = "idle"
    PAUSED = "paused"
    AWAITING_BREAK = "awaiting_break"


@dataclass(frozen=True)
class TimerSnapshot:
    """画面表示に必要なタイマーの読み取り専用状態。"""

    state: TimerState
    active_seconds: float
    remaining_seconds: int
    progress_index: int
    progress_symbol: str
    label: str


class PomodoroTimer:
    """入力のアイドル時間から作業・休憩状態を管理する。"""

    PROGRESS_SYMBOLS = ("○", "◔", "◑", "◕", "●")

    def __init__(
        self,
        *,
        work_threshold_sec: int,
        break_threshold_sec: int,
        active_limit_ms: int,
        now: float,
    ) -> None:
        if work_threshold_sec <= 0:
            raise ValueError("work_threshold_sec は正の値にしてください")
        if break_threshold_sec <= 0:
            raise ValueError("break_threshold_sec は正の値にしてください")
        if active_limit_ms < 0:
            raise ValueError("active_limit_ms は0以上にしてください")

        self.work_threshold_sec = work_threshold_sec
        self.break_threshold_sec = break_threshold_sec
        self.active_limit_ms = active_limit_ms
        self.active_seconds = 0.0
        self.paused = False
        self.was_on_break = True
        self.awaiting_break = False
        self.is_idle = False
        self._last_update = now

    def update(self, *, idle_ms: int, now: float) -> tuple[TimerEvent, ...]:
        """現在のアイドル時間を反映し、発生した出来事を返す。"""

        elapsed = max(0.0, now - self._last_update)
        self._last_update = now
        was_idle = self.is_idle
        self.is_idle = idle_ms > self.active_limit_ms

        if self.paused:
            return ()

        if self.awaiting_break:
            if self.is_idle and idle_ms // 1000 >= self.break_threshold_sec:
                self.active_seconds = 0.0
                self.awaiting_break = False
                self.was_on_break = True
                return (TimerEvent.BREAK_DETECTED,)
            return ()

        if self.is_idle:
            events: list[TimerEvent] = []
            if not was_idle:
                events.append(TimerEvent.IDLE_STARTED)
            if idle_ms // 1000 >= self.break_threshold_sec and not self.was_on_break:
                self.active_seconds = 0.0
                self.was_on_break = True
                events.append(TimerEvent.BREAK_DETECTED)
            return tuple(events)

        events = []
        if self.was_on_break:
            self.was_on_break = False
            events.append(TimerEvent.WORK_STARTED)
        elif was_idle:
            events.append(TimerEvent.ACTIVITY_RESUMED)
        else:
            self.active_seconds += elapsed

        if self.active_seconds >= self.work_threshold_sec:
            self.active_seconds = float(self.work_threshold_sec)
            self.awaiting_break = True
            events.append(TimerEvent.WORK_LIMIT_REACHED)

        return tuple(events)

    def reset(self, *, now: float) -> tuple[TimerEvent, ...]:
        """タイマーを0に戻し、その場で新しい作業を開始する。"""

        self.active_seconds = 0.0
        self.paused = False
        self.was_on_break = False
        self.awaiting_break = False
        self.is_idle = False
        self._last_update = now
        return (TimerEvent.WORK_STARTED,)

    def set_paused(self, paused: bool, *, now: float) -> None:
        """手動停止を切り替え、停止中の経過時間を作業時間から除外する。"""

        self.paused = paused
        self._last_update = now

    def export_state(self) -> dict[str, Any]:
        """別プロセスでも復元できるタイマー状態を返す。"""

        return {
            "active_seconds": self.active_seconds,
            "paused": self.paused,
            "was_on_break": self.was_on_break,
            "awaiting_break": self.awaiting_break,
            "is_idle": self.is_idle,
        }

    def restore_state(self, state: dict[str, Any], *, now: float) -> None:
        """保存済み状態を検証し、現在のタイマーへ反映する。"""

        try:
            active_seconds = float(state.get("active_seconds", 0))
        except (TypeError, ValueError):
            active_seconds = 0.0
        self.active_seconds = min(
            float(self.work_threshold_sec),
            max(0.0, active_seconds),
        )
        self.paused = state.get("paused") is True
        self.was_on_break = state.get("was_on_break") is True
        self.awaiting_break = state.get("awaiting_break") is True
        self.is_idle = state.get("is_idle") is True
        if self.awaiting_break:
            self.active_seconds = float(self.work_threshold_sec)
            self.was_on_break = False
        self._last_update = now

    def snapshot(self, *, now: float | None = None) -> TimerSnapshot:
        """現在の表示内容を返す。"""

        display_active_seconds = self.active_seconds
        if (
            now is not None
            and not self.paused
            and not self.awaiting_break
            and not self.was_on_break
            and not self.is_idle
        ):
            display_active_seconds += max(0.0, now - self._last_update)
        remaining = max(0, math.ceil(self.work_threshold_sec - display_active_seconds))
        ratio = min(1.0, display_active_seconds / self.work_threshold_sec)
        progress_index = int(ratio * (len(self.PROGRESS_SYMBOLS) - 1))
        symbol = self.PROGRESS_SYMBOLS[progress_index]

        if self.paused:
            state = TimerState.PAUSED
            label = "❚❚ Paused"
        elif self.awaiting_break:
            state = TimerState.AWAITING_BREAK
            label = "Take a break!!"
        else:
            if self.was_on_break:
                state = TimerState.READY
            elif self.is_idle:
                state = TimerState.IDLE
            else:
                state = TimerState.WORKING
            minutes, seconds = divmod(remaining, 60)
            label = f"{symbol} {minutes:02d}:{seconds:02d}"

        return TimerSnapshot(
            state=state,
            active_seconds=display_active_seconds,
            remaining_seconds=remaining,
            progress_index=progress_index,
            progress_symbol=symbol,
            label=label,
        )
