"""Windowsのmpv起動と名前付きパイプ操作。"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import time
import winreg


class WindowsMpvAdapter:
    def __init__(self) -> None:
        self.pipe_path = rf"\\.\pipe\pomowatcher-mpv-{os.getpid()}"
        self.process: subprocess.Popen[bytes] | None = None

    @staticmethod
    def _find_executable() -> str | None:
        command = shutil.which("mpv")
        if command is not None:
            return command
        registry_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\mpv.exe"
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(root, registry_path) as key:
                    value, _ = winreg.QueryValueEx(key, None)
            except OSError:
                continue
            if value and Path(value).is_file():
                return str(value)
        candidates = (
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "mpv" / "mpv.exe",
            Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
            / "MPV Player"
            / "mpv.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "mpv" / "mpv.exe",
        )
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        return None

    def launch(self, *, kind: str, path: Path, volume: int) -> subprocess.Popen[bytes]:
        executable = self._find_executable()
        if executable is None:
            raise FileNotFoundError("mpvが見つかりません。install.ps1を再実行してください")
        command = [
            executable,
            "--no-video",
            "--really-quiet",
            f"--volume={volume}",
            f"--input-ipc-server={self.pipe_path}",
        ]
        if kind == "dir":
            command.extend(["--shuffle", "--loop-playlist=inf"])
        else:
            command.append("--loop-file=inf")
        command.append(str(path))
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return self.process

    def send(self, command: list[object]) -> bool:
        payload = json.dumps({"command": command}, ensure_ascii=False).encode("utf-8") + b"\n"
        last_error: OSError | None = None
        for _ in range(10):
            try:
                with open(self.pipe_path, "r+b", buffering=0) as pipe:
                    pipe.write(payload)
                return True
            except OSError as exc:
                last_error = exc
                time.sleep(0.05)
        logging.warning("mpv操作に失敗しました: %s", last_error)
        return False

    def cleanup(self) -> None:
        self.process = None
