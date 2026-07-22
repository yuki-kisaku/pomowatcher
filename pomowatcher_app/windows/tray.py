"""Windowsの通知領域アイコン。"""

from __future__ import annotations

from collections.abc import Callable

import pystray
from pystray._util import win32 as pystray_win32
from PIL import Image, ImageDraw

from ..timer import TimerState


class WindowsTrayIcon(pystray.Icon):
    """左右どちらのクリックでもアプリ側のメニューを開くトレイアイコン。"""

    def __init__(
        self,
        *args,
        on_menu_requested: Callable[[], None],
        **kwargs,
    ) -> None:
        self._on_menu_requested = on_menu_requested
        super().__init__(*args, **kwargs)

    def _on_notify(self, wparam: int, lparam: int) -> None:
        if lparam in (
            pystray_win32.WM_LBUTTONUP,
            pystray_win32.WM_RBUTTONUP,
        ):
            self._on_menu_requested()
            return
        super()._on_notify(wparam, lparam)


def render_tray_icon(state: TimerState, progress_index: int) -> Image.Image:
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    box = (10, 10, 54, 54)
    draw.ellipse(box, outline=(135, 145, 160, 255), width=7)
    if state == TimerState.PAUSED:
        draw.rectangle((22, 20, 27, 44), fill=(185, 190, 200, 255))
        draw.rectangle((37, 20, 42, 44), fill=(185, 190, 200, 255))
    elif state == TimerState.AWAITING_BREAK:
        draw.ellipse(box, fill=(230, 126, 34, 255))
        draw.rectangle((30, 20, 34, 36), fill=(255, 255, 255, 255))
        draw.ellipse((30, 41, 34, 45), fill=(255, 255, 255, 255))
    elif progress_index > 0:
        end = -90 + 90 * progress_index
        draw.arc(box, start=-90, end=end, fill=(62, 156, 255, 255), width=7)
    return image
