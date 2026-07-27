"""Linuxの作業上限通知。"""

import logging
import subprocess


class LinuxNotifier:
    def work_limit_reached(self) -> None:
        subprocess.run(
            [
                "notify-send",
                "--urgency=normal",
                "50 Minutes Complete",
                "Time for a break!",
            ],
            check=False,
        )
        try:
            subprocess.run(
                [
                    "canberra-gtk-play",
                    "-f",
                    "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga",
                ],
                check=False,
            )
        except FileNotFoundError:
            logging.warning("効果音を再生できません: canberra-gtk-playが見つかりません")
