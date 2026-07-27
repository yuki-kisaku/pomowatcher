"""macOS通知。"""

import subprocess


class MacNotifier:
    def work_limit_reached(self) -> None:
        subprocess.run(
            [
                "osascript",
                "-e",
                'display notification "Time for a break!" '
                'with title "50 Minutes Complete" sound name "Glass"',
            ],
            check=False,
        )
