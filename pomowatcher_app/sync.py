"""タイマー状態のローカル保存とLAN同期。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import platform
import socket
import time
from typing import Any
from urllib import error, request
import uuid

from .timer import PomodoroTimer


STATE_VERSION = 1


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Any] | None:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def save(self, value: dict[str, Any]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = self.path.with_suffix(".tmp")
            temporary_path.write_text(
                json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary_path.replace(self.path)
        except OSError as exc:
            logging.warning("タイマー状態を保存できません: %s", exc)


class SyncClient:
    def __init__(self, server_url: str, token: str = "") -> None:
        self.url = server_url.rstrip("/") + "/v1/state"
        self.token = token

    def _request(self, method: str, payload: dict[str, Any] | None = None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        call = request.Request(self.url, data=data, headers=headers, method=method)
        with request.urlopen(call, timeout=2) as response:
            if response.status == 204:
                return None
            return json.loads(response.read().decode("utf-8"))

    def fetch(self) -> dict[str, Any] | None:
        try:
            value = self._request("GET")
            return value if isinstance(value, dict) else None
        except (OSError, error.URLError, json.JSONDecodeError):
            return None

    def push(self, value: dict[str, Any]) -> dict[str, Any] | None:
        try:
            result = self._request("PUT", value)
            return result if isinstance(result, dict) else None
        except (OSError, error.URLError, json.JSONDecodeError):
            return None


class StateCoordinator:
    """ローカルを常に保存し、利用可能なら共有サーバーとも同期する。"""

    def __init__(
        self,
        *,
        timer: PomodoroTimer,
        store: StateStore,
        sync_client: SyncClient | None,
        device_id_path: Path,
        now: float,
    ) -> None:
        self.timer = timer
        self.store = store
        self.sync_client = sync_client
        self.device_id = self._load_device_id(device_id_path)
        self.revision = 0
        self.updated_at = 0.0
        self.last_sync_at = 0.0
        local = store.load()
        if local:
            self._apply(local, now=now)

    @staticmethod
    def _load_device_id(path: Path) -> str:
        try:
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
        except OSError:
            pass
        value = f"{platform.system().lower()}-{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value + "\n", encoding="utf-8")
        except OSError:
            pass
        return value

    def _document(self) -> dict[str, Any]:
        return {
            "schema_version": STATE_VERSION,
            "revision": self.revision,
            "updated_at": self.updated_at,
            "device_id": self.device_id,
            "timer": self.timer.export_state(),
        }

    def _apply(self, value: dict[str, Any], *, now: float) -> bool:
        timer_state = value.get("timer")
        if not isinstance(timer_state, dict):
            return False
        try:
            revision = int(value.get("revision", 0))
            updated_at = float(value.get("updated_at", 0))
        except (TypeError, ValueError):
            return False
        self.timer.restore_state(timer_state, now=now)
        self.revision = max(0, revision)
        self.updated_at = max(0.0, updated_at)
        self.store.save(self._document())
        return True

    def save_local(self) -> None:
        self.updated_at = time.time()
        self.store.save(self._document())

    def synchronize(
        self,
        *,
        now: float,
        allow_push: bool = True,
        force_push: bool = False,
    ) -> bool:
        self.save_local()
        if self.sync_client is None:
            return False
        monotonic_now = time.monotonic()
        if not force_push and monotonic_now - self.last_sync_at < 5:
            return False
        self.last_sync_at = monotonic_now
        remote = self.sync_client.fetch()
        if remote is not None:
            remote_revision = int(remote.get("revision", 0))
            remote_updated = float(remote.get("updated_at", 0))
            if remote_revision > self.revision or remote_updated > self.updated_at:
                self._apply(remote, now=now)
                return True
        if allow_push and (
            force_push
            or remote is None
            or self.updated_at >= float(remote.get("updated_at", 0))
        ):
            result = self.sync_client.push(self._document())
            if result is not None:
                self.revision = int(result.get("revision", self.revision))
                self.updated_at = float(result.get("updated_at", self.updated_at))
                self.store.save(self._document())
        return False
