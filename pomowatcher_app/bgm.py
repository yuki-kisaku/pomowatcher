"""OS共通のBGM選択と再生状態管理。"""

from __future__ import annotations

import logging
from pathlib import Path
import subprocess
from typing import Protocol

from .settings import normalize_volume


AUDIO_EXTENSIONS = {".mp3", ".ogg", ".flac", ".m4a", ".opus", ".webm", ".wav", ".aac"}


class MpvAdapter(Protocol):
    """OSごとのmpv起動方法とIPC方法が満たすインターフェース。"""

    def launch(self, *, kind: str, path: Path, volume: int) -> subprocess.Popen[bytes]: ...

    def send(self, command: list[object]) -> bool: ...

    def cleanup(self) -> None: ...


class MpvBgmPlayer:
    """BGMの探索・停止理由・音量を一つの小さなインターフェースで扱う。"""

    def __init__(
        self,
        *,
        adapter: MpvAdapter,
        bgm_dir: Path,
        file_candidates: tuple[Path, ...],
        muted: bool,
        volume: int,
    ) -> None:
        self.adapter = adapter
        self.bgm_dir = bgm_dir
        self.file_candidates = file_candidates
        self.muted = muted
        self.volume = normalize_volume(volume)
        self.process: subprocess.Popen[bytes] | None = None
        self.paused_reasons: set[str] = {"mute"} if muted else set()

    @property
    def process_id(self) -> int | None:
        return self.process.pid if self.is_running() else None

    def _find_target(self) -> tuple[str, Path] | None:
        if self.bgm_dir.is_dir():
            files = sorted(
                path for path in self.bgm_dir.iterdir() if path.suffix.lower() in AUDIO_EXTENSIONS
            )
            if files:
                return ("dir", self.bgm_dir)
        for path in self.file_candidates:
            if path.is_file():
                return ("file", path)
        return None

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self) -> bool:
        if self.muted or self.paused_reasons or self.is_running():
            return False
        target = self._find_target()
        if target is None:
            logging.debug("BGMが見つかりません: %s", self.bgm_dir)
            return False
        kind, path = target
        try:
            self.process = self.adapter.launch(kind=kind, path=path, volume=self.volume)
        except OSError as exc:
            logging.warning("BGMを開始できません: %s", exc)
            self.process = None
            return False
        logging.info("BGM再生開始: %s (%s)", path, kind)
        return True

    def pause(self, reason: str) -> bool:
        if reason in self.paused_reasons:
            return False
        if self.is_running() and not self.paused_reasons:
            if not self.adapter.send(["set_property", "pause", True]):
                return False
        self.paused_reasons.add(reason)
        logging.info("BGM一時停止（%s）", reason)
        return True

    def release(self, reason: str) -> bool:
        if reason not in self.paused_reasons:
            return False
        self.paused_reasons.remove(reason)
        if self.paused_reasons or self.muted or not self.is_running():
            return False
        if not self.adapter.send(["set_property", "pause", False]):
            return False
        logging.info("BGM再開")
        return True

    def set_muted(self, muted: bool) -> None:
        self.muted = muted
        if muted:
            self.pause("mute")
        else:
            self.release("mute")

    def set_volume(self, volume: int) -> int:
        self.volume = normalize_volume(volume)
        if self.is_running():
            self.adapter.send(["set_property", "volume", self.volume])
        logging.info("BGM音量 %s%%", self.volume)
        return self.volume

    def next_track(self) -> bool:
        if self.muted or self.paused_reasons or not self.is_running():
            return False
        if not self.adapter.send(["playlist-next", "weak"]):
            return False
        logging.info("BGM次の曲")
        return True

    def stop(self) -> None:
        process = self.process
        self.process = None
        if process is None:
            self.adapter.cleanup()
            return
        try:
            process.terminate()
            process.wait(timeout=2)
        except (subprocess.TimeoutExpired, ProcessLookupError):
            try:
                process.kill()
                process.wait(timeout=2)
            except (subprocess.TimeoutExpired, ProcessLookupError):
                pass
        self.adapter.cleanup()
        logging.info("BGM停止")
