#!/usr/bin/env python3
"""Linux版の互換起動ファイル。"""

from pathlib import Path
import sys


WORK_THRESHOLD_SEC = 50 * 60
IDLE_THRESHOLD_SEC = 10 * 60
CHECK_INTERVAL_SEC = 30
ACTIVE_LIMIT_MS = 30 * 1000


repo_dir = Path(__file__).resolve().parent
if str(repo_dir) not in sys.path:
    sys.path.insert(0, str(repo_dir))

from pomowatcher_app.linux.app import main


if __name__ == "__main__":
    raise SystemExit(
        main(
            work_threshold_sec=WORK_THRESHOLD_SEC,
            idle_threshold_sec=IDLE_THRESHOLD_SEC,
            check_interval_sec=CHECK_INTERVAL_SEC,
            active_limit_ms=ACTIVE_LIMIT_MS,
        )
    )
