"""macOS通知。"""

import subprocess


class MacNotifier:
    def work_limit_reached(self) -> None:
        self._show("50 Minutes Complete", "Time for a break!")

    def break_reminder(self) -> None:
        self._show("Over 50 Minutes", "Take a break!")

    def _show(self, title: str, body: str) -> None:
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display notification "{body}" '
                f'with title "{title}" sound name "Glass"',
            ],
            check=False,
        )
