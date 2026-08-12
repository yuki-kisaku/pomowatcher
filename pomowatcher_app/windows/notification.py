"""Windows通知。"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import subprocess

from windows_toasts import Toast, ToastAudio, WindowsToaster

from ..settings import NOTIFY_VOLUME_MAX, normalize_notify_volume
from .bgm import find_mpv_executable


SOUND_PATH = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Media" / "Alarm03.wav"


class WindowsNotifier:
    """トーストは無音にして、音量を指定できるmpvで通知音を鳴らす。"""

    def __init__(self, volume: int) -> None:
        self._toaster = WindowsToaster("Pomowatcher")
        self.volume = normalize_notify_volume(volume)

    def work_limit_reached(self) -> None:
        self._show("50 Minutes Complete", "Time for a break!")

    def break_reminder(self) -> None:
        self._show("Over 50 Minutes", "Take a break!")

    def _show(self, title: str, body: str) -> None:
        toast = Toast()
        toast.text_fields = [title, body]
        toast.audio = ToastAudio(silent=True)
        try:
            self._toaster.show_toast(toast)
        except Exception as exc:
            logging.warning("通知を表示できません: %s", exc)
        self._play_sound()

    def _play_sound(self) -> None:
        executable = find_mpv_executable()
        if executable is None:
            logging.warning("通知音を再生できません: mpvが見つかりません")
            return
        try:
            subprocess.Popen(
                [
                    executable,
                    "--no-video",
                    "--really-quiet",
                    f"--volume-max={NOTIFY_VOLUME_MAX}",
                    f"--volume={self.volume}",
                    str(SOUND_PATH),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except OSError as exc:
            logging.warning("通知音を再生できません: %s", exc)
