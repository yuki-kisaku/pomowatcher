"""Windowsの入力アイドル時間取得。"""

from __future__ import annotations

import ctypes


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def configure_dpi_awareness() -> None:
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        pass


def get_idle_ms() -> int:
    """現在のWindowsセッションで最後に入力されてからの時間を返す。"""

    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        raise ctypes.WinError()
    ctypes.windll.kernel32.GetTickCount.restype = ctypes.c_uint
    current = ctypes.windll.kernel32.GetTickCount()
    return ctypes.c_uint(current - info.dwTime).value
