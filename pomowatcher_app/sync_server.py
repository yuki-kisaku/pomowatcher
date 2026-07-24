"""Ubuntuノートで動かすPomowatcher LAN同期サーバー。"""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any


class StateDatabase:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS shared_state "
            "(id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, "
            "updated_at REAL NOT NULL, document TEXT NOT NULL)"
        )
        self.connection.commit()

    def get(self) -> dict[str, Any] | None:
        with self.lock:
            row = self.connection.execute(
                "SELECT revision, updated_at, document FROM shared_state WHERE id=1"
            ).fetchone()
        if row is None:
            return None
        value = json.loads(row[2])
        value["revision"] = row[0]
        value["updated_at"] = row[1]
        return value

    def put(self, value: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            row = self.connection.execute(
                "SELECT revision FROM shared_state WHERE id=1"
            ).fetchone()
            revision = (row[0] if row else 0) + 1
            updated_at = time.time()
            value = dict(value)
            value["revision"] = revision
            value["updated_at"] = updated_at
            document = json.dumps(value, ensure_ascii=False)
            self.connection.execute(
                "INSERT INTO shared_state(id, revision, updated_at, document) "
                "VALUES(1, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                "revision=excluded.revision, updated_at=excluded.updated_at, "
                "document=excluded.document",
                (revision, updated_at, document),
            )
            self.connection.commit()
        return value

    def close(self) -> None:
        with self.lock:
            self.connection.close()


def make_handler(database: StateDatabase, token: str):
    class Handler(BaseHTTPRequestHandler):
        def _authorized(self) -> bool:
            return not token or self.headers.get("Authorization") == f"Bearer {token}"

        def _json(self, status: int, value: dict[str, Any]) -> None:
            body = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/health":
                self._json(200, {"status": "ok"})
                return
            if self.path != "/v1/state" or not self._authorized():
                self.send_error(401 if not self._authorized() else 404)
                return
            value = database.get()
            if value is None:
                self.send_response(204)
                self.end_headers()
            else:
                self._json(200, value)

        def do_PUT(self) -> None:
            if self.path != "/v1/state" or not self._authorized():
                self.send_error(401 if not self._authorized() else 404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                value = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(value, dict) or not isinstance(value.get("timer"), dict):
                    raise ValueError
            except (ValueError, json.JSONDecodeError):
                self.send_error(400)
                return
            self._json(200, database.put(value))

        def log_message(self, format: str, *args: object) -> None:
            logging.info("%s - %s", self.client_address[0], format % args)

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description="Pomowatcher LAN同期サーバー")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--database",
        type=Path,
        default=Path.home() / ".local" / "share" / "pomowatcher" / "sync.db",
    )
    parser.add_argument("--token", default=os.environ.get("POMOWATCHER_SYNC_TOKEN", ""))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    database = StateDatabase(args.database)
    server = ThreadingHTTPServer(
        (args.host, args.port),
        make_handler(database, args.token),
    )
    logging.info("同期サーバー開始: http://%s:%s", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        database.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
