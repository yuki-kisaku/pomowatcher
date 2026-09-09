#!/usr/bin/env python3
"""旧Linux版のsystemd journalから作業時間DBを復元する。"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sqlite3
import sys
from typing import Iterable, TextIO


ACTIVE_LIMIT_MS = 30_000
GAP_LIMIT_SEC = 90
_IDLE_PATTERN = re.compile(r"(?:^| )idle_ms=(\d+), is_idle=(?:True|False)$")


@dataclass
class Session:
    started_at: float
    ended_at: float


def parse_journal(lines: Iterable[str]) -> list[Session]:
    """journalctl -o jsonの出力から操作中の区間を復元する。"""

    sessions: list[Session] = []
    active: Session | None = None
    opened_at: float | None = None
    last_sample_at: float | None = None
    paused = False

    def close(ended_at: float) -> None:
        nonlocal active
        if active is None:
            return
        active.ended_at = max(active.ended_at, ended_at)
        if active.ended_at > active.started_at:
            sessions.append(active)
        active = None

    for line in lines:
        try:
            record = json.loads(line)
            current = int(record["__REALTIME_TIMESTAMP"]) / 1_000_000
            message = str(record.get("MESSAGE", ""))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue

        if message.endswith("pomowatcher 開始"):
            close(last_sample_at if last_sample_at is not None else current)
            opened_at = current
            last_sample_at = None
            paused = False
            continue
        if message.endswith("一時停止"):
            close(current)
            paused = True
            last_sample_at = current
            continue
        if message.endswith("再開"):
            paused = False
            last_sample_at = current
            continue

        match = _IDLE_PATTERN.search(message)
        if match is None or paused:
            continue
        idle_ms = int(match.group(1))

        if (
            active is not None
            and last_sample_at is not None
            and current - last_sample_at > GAP_LIMIT_SEC
        ):
            close(last_sample_at)

        if idle_ms <= ACTIVE_LIMIT_MS:
            if active is None:
                earliest = opened_at if opened_at is not None else current
                if last_sample_at is not None:
                    earliest = last_sample_at
                started_at = max(earliest, current - idle_ms / 1000)
                active = Session(started_at, current)
            else:
                active.ended_at = max(active.ended_at, current)
        elif active is not None:
            close(current - (idle_ms - ACTIVE_LIMIT_MS) / 1000)

        opened_at = current if opened_at is None else opened_at
        last_sample_at = current

    close(last_sample_at if last_sample_at is not None else 0)
    return sessions


def write_database(path: Path, sessions: list[Session]) -> None:
    """空の作業履歴DBへ復元結果を書き込む。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS work_sessions (
                id INTEGER PRIMARY KEY,
                started_at REAL NOT NULL,
                ended_at REAL NOT NULL
            )
            """
        )
        count = connection.execute("SELECT COUNT(*) FROM work_sessions").fetchone()[0]
        if count:
            raise RuntimeError(f"既存の作業履歴が{count}件あるため中止します")
        connection.executemany(
            "INSERT INTO work_sessions (started_at, ended_at) VALUES (?, ?)",
            ((session.started_at, session.ended_at) for session in sessions),
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS work_sessions_time
            ON work_sessions (ended_at, started_at)
            """
        )
        connection.commit()
    finally:
        connection.close()


def main(stdin: TextIO = sys.stdin) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    sessions = parse_journal(stdin)
    seconds = sum(session.ended_at - session.started_at for session in sessions)
    print(f"復元区間: {len(sessions)}件 / {seconds / 3600:.2f}時間")
    if not args.dry_run:
        write_database(args.database, sessions)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
