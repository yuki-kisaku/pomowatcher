"""Linuxのmpv起動とUnixソケット操作。"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import socket
import subprocess


class LinuxMpvAdapter:
    def __init__(self) -> None:
        self.ipc_path = Path(f"/tmp/pomowatcher-mpv-{os.getuid()}.sock")

    def launch(self, *, kind: str, path: Path, volume: int) -> subprocess.Popen[bytes]:
        self.cleanup()
        command = [
            "mpv",
            "--no-video",
            "--really-quiet",
            f"--volume={volume}",
            f"--input-ipc-server={self.ipc_path}",
        ]
        if kind == "dir":
            command.extend(["--shuffle", "--loop-playlist=inf"])
        else:
            command.append("--loop-file=inf")
        command.append(str(path))
        try:
            return subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                "mpvが見つかりません。sudo apt install mpvでインストールしてください"
            ) from exc

    def send(self, command: list[object]) -> bool:
        payload = json.dumps({"command": command}, ensure_ascii=False).encode("utf-8") + b"\n"
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(1)
                client.connect(str(self.ipc_path))
                client.sendall(payload)
            return True
        except (FileNotFoundError, ConnectionRefusedError, OSError) as exc:
            logging.warning("mpv操作に失敗しました: %s", exc)
            return False

    def cleanup(self) -> None:
        try:
            self.ipc_path.unlink()
        except FileNotFoundError:
            pass
