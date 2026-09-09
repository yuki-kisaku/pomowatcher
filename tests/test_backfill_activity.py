import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts.backfill_activity_from_journal import parse_journal, write_database


def entry(seconds: float, message: str) -> str:
    return json.dumps(
        {
            "__REALTIME_TIMESTAMP": str(int(seconds * 1_000_000)),
            "MESSAGE": message,
        }
    )


class ParseJournalTest(unittest.TestCase):
    def test_restores_active_session_and_closes_at_idle_boundary(self) -> None:
        sessions = parse_journal(
            [
                entry(100, "pomowatcher 開始"),
                entry(101, "idle_ms=1000, is_idle=False"),
                entry(131, "idle_ms=1000, is_idle=False"),
                entry(161, "idle_ms=31000, is_idle=True"),
            ]
        )

        self.assertEqual(len(sessions), 1)
        self.assertEqual((sessions[0].started_at, sessions[0].ended_at), (100, 160))

    def test_does_not_bridge_service_gap(self) -> None:
        sessions = parse_journal(
            [
                entry(100, "idle_ms=0, is_idle=False"),
                entry(130, "idle_ms=0, is_idle=False"),
                entry(500, "idle_ms=0, is_idle=False"),
            ]
        )

        self.assertEqual(
            [(session.started_at, session.ended_at) for session in sessions],
            [(100, 130)],
        )

    def test_pause_closes_session_and_ignores_samples_until_resume(self) -> None:
        sessions = parse_journal(
            [
                entry(100, "idle_ms=0, is_idle=False"),
                entry(130, "一時停止"),
                entry(160, "idle_ms=0, is_idle=False"),
                entry(190, "再開"),
                entry(220, "idle_ms=0, is_idle=False"),
                entry(250, "idle_ms=31000, is_idle=True"),
            ]
        )

        self.assertEqual(
            [(session.started_at, session.ended_at) for session in sessions],
            [(100, 130), (220, 249)],
        )


class WriteDatabaseTest(unittest.TestCase):
    def test_refuses_to_append_to_existing_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "activity.sqlite3"
            sessions = parse_journal(
                [entry(100, "idle_ms=0, is_idle=False"), entry(130, "idle_ms=31000, is_idle=True")]
            )
            write_database(path, sessions)

            connection = sqlite3.connect(path)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM work_sessions").fetchone()[0], 1)
            connection.close()
            with self.assertRaises(RuntimeError):
                write_database(path, sessions)


if __name__ == "__main__":
    unittest.main()
