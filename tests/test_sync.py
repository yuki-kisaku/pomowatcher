import tempfile
import time
import unittest
from pathlib import Path

from pomowatcher_app.sync import StateCoordinator, StateStore
from pomowatcher_app.sync_server import StateDatabase
from pomowatcher_app.timer import PomodoroTimer, TimerState


class StateCoordinatorTest(unittest.TestCase):
    def make_timer(self, now: float = 0) -> PomodoroTimer:
        return PomodoroTimer(
            work_threshold_sec=100,
            break_threshold_sec=10,
            active_limit_ms=3_000,
            now=now,
        )

    def test_タイマー状態を保存して復元できる(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timer = self.make_timer()
            timer.update(idle_ms=0, now=1)
            timer.update(idle_ms=0, now=11)
            first = StateCoordinator(
                timer=timer,
                store=StateStore(root / "state.json"),
                sync_client=None,
                device_id_path=root / "device-id",
                now=11,
            )
            first.save_local()

            restored = self.make_timer(now=20)
            StateCoordinator(
                timer=restored,
                store=StateStore(root / "state.json"),
                sync_client=None,
                device_id_path=root / "device-id",
                now=20,
            )

            self.assertEqual(restored.snapshot().state, TimerState.WORKING)
            self.assertEqual(restored.snapshot().active_seconds, 10)

    def test_壊れた状態値を安全な範囲へ補正する(self) -> None:
        timer = self.make_timer()
        timer.restore_state({"active_seconds": 9999}, now=1)
        self.assertEqual(timer.snapshot().active_seconds, 100)


class StateDatabaseTest(unittest.TestCase):
    def test_更新ごとにリビジョンが増える(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = StateDatabase(Path(directory) / "sync.db")
            value = {"timer": {"active_seconds": 1}}

            first = database.put(value)
            time.sleep(0.001)
            second = database.put(value)

            self.assertEqual(first["revision"], 1)
            self.assertEqual(second["revision"], 2)
            self.assertEqual(database.get()["revision"], 2)
            database.close()


if __name__ == "__main__":
    unittest.main()
