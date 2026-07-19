import unittest

from pomowatcher_app.timer import PomodoroTimer, TimerEvent, TimerState


class PomodoroTimerTest(unittest.TestCase):
    def make_timer(self) -> PomodoroTimer:
        return PomodoroTimer(
            work_threshold_sec=100,
            break_threshold_sec=10,
            active_limit_ms=3_000,
            now=0,
        )

    def test_最初の入力で作業を開始する(self) -> None:
        timer = self.make_timer()

        events = timer.update(idle_ms=0, now=1)

        self.assertEqual(events, (TimerEvent.WORK_STARTED,))
        self.assertEqual(timer.snapshot().state, TimerState.WORKING)
        self.assertEqual(timer.snapshot().active_seconds, 0)

    def test_操作中の経過時間を加算する(self) -> None:
        timer = self.make_timer()
        timer.update(idle_ms=0, now=1)

        timer.update(idle_ms=500, now=6)

        self.assertEqual(timer.snapshot().active_seconds, 5)
        self.assertEqual(timer.snapshot().label, "○ 01:35")

    def test_定期更新の間も表示上の残り時間を進める(self) -> None:
        timer = self.make_timer()
        timer.update(idle_ms=0, now=1)

        snapshot = timer.snapshot(now=6)

        self.assertEqual(snapshot.active_seconds, 5)
        self.assertEqual(snapshot.label, "○ 01:35")

    def test_短い離席では時間を保って再開する(self) -> None:
        timer = self.make_timer()
        timer.update(idle_ms=0, now=1)
        timer.update(idle_ms=0, now=11)

        idle_events = timer.update(idle_ms=3_001, now=12)
        resume_events = timer.update(idle_ms=0, now=15)

        self.assertEqual(idle_events, (TimerEvent.IDLE_STARTED,))
        self.assertEqual(resume_events, (TimerEvent.ACTIVITY_RESUMED,))
        self.assertEqual(timer.snapshot().active_seconds, 10)

    def test_10分相当の離席でリセットする(self) -> None:
        timer = self.make_timer()
        timer.update(idle_ms=0, now=1)
        timer.update(idle_ms=0, now=11)

        events = timer.update(idle_ms=10_000, now=20)

        self.assertEqual(events, (TimerEvent.IDLE_STARTED, TimerEvent.BREAK_DETECTED))
        self.assertEqual(timer.snapshot().state, TimerState.READY)
        self.assertEqual(timer.snapshot().active_seconds, 0)

    def test_作業上限で休憩待ちになる(self) -> None:
        timer = self.make_timer()
        timer.update(idle_ms=0, now=1)

        events = timer.update(idle_ms=0, now=101)

        self.assertEqual(events, (TimerEvent.WORK_LIMIT_REACHED,))
        self.assertEqual(timer.snapshot().state, TimerState.AWAITING_BREAK)
        self.assertEqual(timer.snapshot().label, "Take a break!!")

    def test_休憩待ちは規定時間の離席まで解除しない(self) -> None:
        timer = self.make_timer()
        timer.update(idle_ms=0, now=1)
        timer.update(idle_ms=0, now=101)

        self.assertEqual(timer.update(idle_ms=0, now=105), ())
        self.assertEqual(timer.snapshot().state, TimerState.AWAITING_BREAK)

        events = timer.update(idle_ms=10_000, now=111)
        self.assertEqual(events, (TimerEvent.BREAK_DETECTED,))
        self.assertEqual(timer.snapshot().state, TimerState.READY)

    def test_手動停止中の時間を加算しない(self) -> None:
        timer = self.make_timer()
        timer.update(idle_ms=0, now=1)
        timer.update(idle_ms=0, now=6)
        timer.set_paused(True, now=6)

        timer.update(idle_ms=0, now=30)
        timer.set_paused(False, now=30)
        timer.update(idle_ms=0, now=35)

        self.assertEqual(timer.snapshot().active_seconds, 10)

    def test_リセットで停止と休憩待ちも解除する(self) -> None:
        timer = self.make_timer()
        timer.update(idle_ms=0, now=1)
        timer.set_paused(True, now=2)

        events = timer.reset(now=3)

        self.assertEqual(events, (TimerEvent.WORK_STARTED,))
        self.assertFalse(timer.paused)
        self.assertEqual(timer.snapshot().state, TimerState.WORKING)


if __name__ == "__main__":
    unittest.main()
