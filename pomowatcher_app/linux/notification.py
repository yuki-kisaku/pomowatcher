"""Linuxの作業上限通知。"""

import logging
import subprocess


class LinuxNotifier:
    def work_limit_reached(self) -> None:
        self._show("50 Minutes Complete", "Time for a break!")

    def break_reminder(self) -> None:
        self._show("Over 50 Minutes", "Take a break!")

    def _show(self, title: str, body: str) -> None:
        subprocess.run(
            [
                "notify-send",
                "--urgency=normal",
                title,
                body,
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
