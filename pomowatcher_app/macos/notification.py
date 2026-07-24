"""macOS通知。"""

import subprocess


class MacNotifier:
    def work_limit_reached(self) -> None:
        subprocess.run(
            [
                "osascript",
                "-e",
                'display notification "そろそろ休憩しましょう！" '
                'with title "作業50分経過" sound name "Glass"',
            ],
            check=False,
        )
