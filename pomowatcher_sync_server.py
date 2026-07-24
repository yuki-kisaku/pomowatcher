#!/usr/bin/env python3
"""Pomowatcher同期サーバー起動ファイル。"""

from pathlib import Path
import sys


repo_dir = Path(__file__).resolve().parent
if str(repo_dir) not in sys.path:
    sys.path.insert(0, str(repo_dir))

from pomowatcher_app.sync_server import main


if __name__ == "__main__":
    raise SystemExit(main())
