"""Windows通知。"""

import logging

from windows_toasts import AudioSource, Toast, ToastAudio, WindowsToaster


class WindowsNotifier:
    def __init__(self) -> None:
        self._toaster = WindowsToaster("Pomowatcher")

    def work_limit_reached(self) -> None:
        toast = Toast()
        toast.text_fields = ["50 Minutes Complete", "Time for a break!"]
        toast.audio = ToastAudio(AudioSource.Reminder)
        try:
            self._toaster.show_toast(toast)
        except Exception as exc:
            logging.warning("通知を表示できません: %s", exc)
