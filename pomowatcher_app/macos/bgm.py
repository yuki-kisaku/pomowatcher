"""macOSのmpv IPC操作。"""

from __future__ import annotations

import json
from pathlib import Path
import socket
import subprocess
import tempfile


class MacMpvAdapter:
    def __init__(self) -> None:
        self.ipc_path = Path(tempfile.gettempdir()) / f"pomowatcher-mpv-{id(self)}.sock"

    def launch(self, *, kind: str, path: Path, volume: int) -> subprocess.Popen[bytes]:
        self.cleanup()
        command = [
            "mpv",
            "--no-video",
            "--no-terminal",
            f"--volume={volume}",
            f"--input-ipc-server={self.ipc_path}",
        ]
        if kind == "dir":
            command.extend(["--shuffle", "--loop-playlist=inf", str(path)])
        else:
            command.extend(["--loop-file=inf", str(path)])
        return subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def send(self, command: list[object]) -> bool:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(1)
                connection.connect(str(self.ipc_path))
                connection.sendall(
                    (json.dumps({"command": command}) + "\n").encode("utf-8")
                )
            return True
        except OSError:
            return False

    def cleanup(self) -> None:
        try:
            self.ipc_path.unlink()
        except FileNotFoundError:
            pass
