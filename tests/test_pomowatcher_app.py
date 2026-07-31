import unittest
from unittest.mock import Mock

from pomowatcher_app.app import PomowatcherController
from pomowatcher_app.settings import AppSettings
from pomowatcher_app.timer import PomodoroTimer


class PomowatcherControllerTest(unittest.TestCase):
    def make_controller(
        self,
        *,
        reminder_interval_sec: int = 300,
    ) -> tuple[PomowatcherController, Mock]:
        bgm = Mock()
        timer = PomodoroTimer(
            work_threshold_sec=100,
            break_threshold_sec=10,
            active_limit_ms=3_000,
            now=0,
            reminder_interval_sec=reminder_interval_sec,
        )
        controller = PomowatcherController(
            timer=timer,
            bgm=bgm,
            settings=AppSettings(),
            save_settings=Mock(),
            notify_work_limit=Mock(),
            notify_break_reminder=Mock(),
        )
        return controller, bgm

    def test_休憩せず作業を続けると通知を出し直す(self) -> None:
        controller, _ = self.make_controller(reminder_interval_sec=20)
        controller.tick(idle_ms=0, now=1)
        controller.tick(idle_ms=0, now=101)
        controller.notify_work_limit.reset_mock()

        controller.tick(idle_ms=0, now=121)
        controller.tick(idle_ms=0, now=141)

        controller.notify_work_limit.assert_not_called()
        self.assertEqual(controller.notify_break_reminder.call_count, 2)

    def test_他メディア再生中は作業を始めてもBGMを再生しない(self) -> None:
        controller, bgm = self.make_controller()
        controller.set_other_media_playing(True)
        controller.tick(idle_ms=0, now=1)
        bgm.start.assert_not_called()
        bgm.pause.assert_any_call("media")

    def test_他メディアの停止後に作業中ならBGMを再開する(self) -> None:
        controller, bgm = self.make_controller()
        controller.set_other_media_playing(True)
        controller.tick(idle_ms=0, now=1)
        bgm.reset_mock()
        controller.set_other_media_playing(False)
        bgm.release.assert_called_once_with("media")
        bgm.start.assert_called_once_with()

    def test_休憩中に他メディアが止まってもBGMを開始しない(self) -> None:
        controller, bgm = self.make_controller()
        controller.set_other_media_playing(True)
        bgm.reset_mock()
        controller.set_other_media_playing(False)
        bgm.start.assert_not_called()

    def test_復元した作業状態でBGMを開始する(self) -> None:
        controller, bgm = self.make_controller()
        controller.timer.restore_state(
            {"active_seconds": 10, "was_on_break": False},
            now=1,
        )

        controller.reconcile_timer_state()

        bgm.start.assert_called_once_with()

    def test_復元した停止状態でBGMを停止する(self) -> None:
        controller, bgm = self.make_controller()
        controller.timer.restore_state(
            {"active_seconds": 10, "paused": True},
            now=1,
        )

        controller.reconcile_timer_state()

        bgm.pause.assert_called_once_with("app")


if __name__ == "__main__":
    unittest.main()
