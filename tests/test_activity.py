from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest

from pomowatcher_app.activity import ActivityLog, format_duration


class ActivityLogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "activity.sqlite3"
        self.logs: list[ActivityLog] = []
        self.base_time = datetime(2026, 7, 27, 9).timestamp()

    def tearDown(self) -> None:
        for activity in self.logs:
            activity.close()
        self.temporary_directory.cleanup()

    def make_log(
        self,
        *,
        now: float | None = None,
        gap_limit_sec: float | None = None,
    ) -> ActivityLog:
        kwargs = {}
        if gap_limit_sec is not None:
            kwargs["gap_limit_sec"] = gap_limit_sec
        activity = ActivityLog(
            self.database_path,
            active_limit_ms=30_000,
            now=self.base_time if now is None else now,
            **kwargs,
        )
        self.logs.append(activity)
        return activity

    def test_操作中の区間を日別に合計する(self) -> None:
        activity = self.make_log(gap_limit_sec=60)
        activity.update(idle_ms=0, paused=False, now=self.base_time)

        self.assertEqual(activity.today_seconds(now=self.base_time + 10), 10)

        activity.update(idle_ms=40_000, paused=False, now=self.base_time + 40)
        self.assertEqual(activity.today_seconds(now=self.base_time + 40), 30)
        activity.close(now=self.base_time + 40)

    def test_休憩後は新しい作業区間として記録する(self) -> None:
        activity = self.make_log(gap_limit_sec=60)
        activity.update(idle_ms=0, paused=False, now=self.base_time)
        activity.update(idle_ms=40_000, paused=False, now=self.base_time + 40)
        activity.update(idle_ms=0, paused=False, now=self.base_time + 100)

        self.assertEqual(activity.today_seconds(now=self.base_time + 110), 40)
        activity.close(now=self.base_time + 110)

    def test_手動停止中を作業時間から除外する(self) -> None:
        activity = self.make_log()
        activity.update(idle_ms=0, paused=False, now=self.base_time)
        activity.update(idle_ms=0, paused=True, now=self.base_time + 10)

        self.assertEqual(activity.today_seconds(now=self.base_time + 100), 10)
        activity.close(now=self.base_time + 100)

    def test_50分を超えても操作中なら集計を続ける(self) -> None:
        activity = self.make_log()
        activity.update(idle_ms=0, paused=False, now=self.base_time)

        self.assertEqual(activity.today_seconds(now=self.base_time + 4_000), 4_000)
        activity.close(now=self.base_time + 4_000)

    def test_作業区間の開始時刻と終了時刻を保存する(self) -> None:
        activity = self.make_log()
        activity.update(idle_ms=0, paused=False, now=self.base_time)
        activity.close(now=self.base_time + 10)

        connection = sqlite3.connect(self.database_path)
        try:
            row = connection.execute(
                "SELECT started_at, ended_at FROM work_sessions"
            ).fetchone()
        finally:
            connection.close()

        self.assertEqual(row, (self.base_time, self.base_time + 10))

    def test_日付をまたぐ作業は現地時刻の0時で分ける(self) -> None:
        day = date(2026, 7, 27)
        midnight = datetime.combine(day, datetime.min.time()).timestamp()
        activity = self.make_log(now=midnight - 10)
        activity.update(idle_ms=0, paused=False, now=midnight - 10)
        activity.update(idle_ms=0, paused=False, now=midnight - 1)

        self.assertEqual(activity.day_seconds(day, now=midnight + 2), 2)
        activity.close(now=midnight + 2)

    def test_更新が長く止まった区間を作業時間に含めない(self) -> None:
        activity = self.make_log()
        activity.update(idle_ms=0, paused=False, now=self.base_time)
        activity.update(idle_ms=0, paused=False, now=self.base_time + 10)

        # スリープ等で1時間止まったあと、操作ありで再開する
        activity.update(idle_ms=0, paused=False, now=self.base_time + 3_610)

        self.assertEqual(activity.today_seconds(now=self.base_time + 3_620), 20)
        activity.close(now=self.base_time + 3_620)

    def test_しきい値以内の更新間隔なら区間を分割しない(self) -> None:
        activity = self.make_log(gap_limit_sec=60)
        activity.update(idle_ms=0, paused=False, now=self.base_time)
        activity.update(idle_ms=0, paused=False, now=self.base_time + 30)

        self.assertEqual(activity.today_seconds(now=self.base_time + 30), 30)
        activity.close(now=self.base_time + 30)

    def test_終了済みの作業区間を再起動後も集計できる(self) -> None:
        activity = self.make_log()
        activity.update(idle_ms=0, paused=False, now=self.base_time)
        activity.close(now=self.base_time + 10)

        restored = self.make_log(now=self.base_time + 100)
        self.assertEqual(restored.today_seconds(now=self.base_time + 100), 10)
        restored.close(now=self.base_time + 100)


class FormatDurationTest(unittest.TestCase):
    def test_1時間未満を分で表示する(self) -> None:
        self.assertEqual(format_duration(59 * 60), "59m")

    def test_1時間以上を時分で表示する(self) -> None:
        self.assertEqual(format_duration((3 * 60 + 25) * 60), "3h 25m")


if __name__ == "__main__":
    unittest.main()
