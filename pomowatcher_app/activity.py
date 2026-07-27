"""PC操作時間の保存と日別集計。"""

from __future__ import annotations

from datetime import date, datetime, time as datetime_time, timedelta
from pathlib import Path
import sqlite3
import time


HEARTBEAT_INTERVAL_SEC = 5


class ActivityLog:
    """操作中の区間をSQLiteへ保存する。"""

    def __init__(
        self,
        path: Path,
        *,
        active_limit_ms: int,
        now: float | None = None,
    ) -> None:
        if active_limit_ms < 0:
            raise ValueError("active_limit_ms は0以上にしてください")

        path.parent.mkdir(parents=True, exist_ok=True)
        self.active_limit_ms = active_limit_ms
        self._connection = sqlite3.connect(path)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS work_sessions (
                id INTEGER PRIMARY KEY,
                started_at REAL NOT NULL,
                ended_at REAL NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE INDEX IF NOT EXISTS work_sessions_time
            ON work_sessions (ended_at, started_at)
            """
        )
        self._connection.commit()
        self._opened_at = time.time() if now is None else now
        self._last_sample_at: float | None = None
        self._last_persisted_at = self._opened_at
        self._active_session_id: int | None = None
        self._closed = False

    def update(self, *, idle_ms: int, paused: bool, now: float | None = None) -> None:
        """現在の操作状態をログへ反映する。"""

        self._ensure_open()
        current = time.time() if now is None else now
        idle_ms = max(0, idle_ms)
        is_active = not paused and idle_ms <= self.active_limit_ms

        if is_active:
            if self._active_session_id is None:
                earliest = self._opened_at
                if self._last_sample_at is not None:
                    earliest = self._last_sample_at
                started_at = max(earliest, current - idle_ms / 1000)
                cursor = self._connection.execute(
                    """
                    INSERT INTO work_sessions (started_at, ended_at)
                    VALUES (?, ?)
                    """,
                    (started_at, current),
                )
                self._active_session_id = int(cursor.lastrowid)
                self._last_persisted_at = current
                self._connection.commit()
            elif current - self._last_persisted_at >= HEARTBEAT_INTERVAL_SEC:
                self._set_active_session_end(current)
        elif self._active_session_id is not None:
            ended_at = current
            if not paused:
                ended_at -= max(0, idle_ms - self.active_limit_ms) / 1000
            self._set_active_session_end(ended_at)
            self._active_session_id = None

        self._last_sample_at = current

    def today_seconds(self, *, now: float | None = None) -> float:
        """PCの現地日付における作業秒数を返す。"""

        current = time.time() if now is None else now
        return self.day_seconds(datetime.fromtimestamp(current).date(), now=current)

    def day_seconds(self, day: date, *, now: float | None = None) -> float:
        """指定した現地日付に重なる作業秒数を返す。"""

        self._ensure_open()
        day_start = datetime.combine(day, datetime_time.min).timestamp()
        day_end = datetime.combine(day + timedelta(days=1), datetime_time.min).timestamp()
        current = time.time() if now is None else now
        total = 0.0
        rows = self._connection.execute(
            """
            SELECT id, started_at, ended_at
            FROM work_sessions
            WHERE (ended_at >= ? OR id = ?) AND started_at < ?
            """,
            (day_start, self._active_session_id, day_end),
        )
        for session_id, started_at, ended_at in rows:
            if session_id == self._active_session_id:
                ended_at = max(ended_at, current)
            total += max(
                0.0,
                min(ended_at, day_end) - max(started_at, day_start),
            )
        return total

    def close(self, *, now: float | None = None) -> None:
        """操作中の区間を閉じてSQLite接続を終了する。"""

        if self._closed:
            return
        if self._active_session_id is not None:
            current = time.time() if now is None else now
            self._set_active_session_end(current)
            self._active_session_id = None
        self._connection.close()
        self._closed = True

    def _set_active_session_end(self, ended_at: float) -> None:
        if self._active_session_id is None:
            return
        self._connection.execute(
            """
            UPDATE work_sessions
            SET ended_at = MAX(ended_at, ?)
            WHERE id = ?
            """,
            (ended_at, self._active_session_id),
        )
        self._connection.commit()
        self._last_persisted_at = ended_at

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("ActivityLogはすでに閉じられています")


def format_duration(seconds: float) -> str:
    """作業秒数を短い英語表記へ変換する。"""

    total_minutes = max(0, int(seconds)) // 60
    hours, minutes = divmod(total_minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"
