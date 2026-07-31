"""Windows通知。"""

import logging

from windows_toasts import AudioSource, Toast, ToastAudio, WindowsToaster


class WindowsNotifier:
    def __init__(self) -> None:
        self._toaster = WindowsToaster("Pomowatcher")

    def work_limit_reached(self) -> None:
        self._show("50 Minutes Complete", "Time for a break!")

    def break_reminder(self) -> None:
        self._show("Over 50 Minutes", "Take a break!")

    def _show(self, title: str, body: str) -> None:
        toast = Toast()
        toast.text_fields = [title, body]
        toast.audio = ToastAudio(AudioSource.Reminder)
        try:
            self._toaster.show_toast(toast)
        except Exception as exc:
            logging.warning("通知を表示できません: %s", exc)
