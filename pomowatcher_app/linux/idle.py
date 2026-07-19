"""Linuxの物理入力デバイス監視。"""

from __future__ import annotations

import logging
import threading
import time

import evdev


_last_input_time = time.monotonic()
_input_lock = threading.Lock()


def _physical_devices() -> list[str]:
    """キーボード・マウス相当の物理デバイスのパスを返す。"""

    event_key = 1 << 1
    event_relative = 1 << 2
    devices: list[str] = []
    current_name = ""
    current_phys: str | None = None
    current_handlers: list[str] = []
    current_events = 0
    with open("/proc/bus/input/devices", encoding="utf-8") as device_file:
        for raw_line in device_file:
            line = raw_line.strip()
            if line.startswith("N:"):
                current_name = line.split("=", 1)[1].strip().strip('"')
            elif line.startswith("P:"):
                current_phys = line.split("=", 1)[1].strip()
            elif line.startswith("H:"):
                current_handlers = line.split("=", 1)[1].split()
            elif line.startswith("B:") and "EV=" in line:
                current_events = int(line.split("=")[1], 16)
            elif line == "":
                is_keyd_keyboard = current_name == "keyd virtual keyboard"
                if (current_phys or is_keyd_keyboard) and (
                    current_events & (event_key | event_relative)
                ):
                    devices.extend(
                        f"/dev/input/{handler}"
                        for handler in current_handlers
                        if handler.startswith("event")
                    )
                current_name = ""
                current_phys = None
                current_handlers = []
                current_events = 0
    return devices


def _watch_device(path: str) -> None:
    global _last_input_time
    try:
        device = evdev.InputDevice(path)
        logging.info("監視開始: %s (%s)", device.name, path)
        for event in device.read_loop():
            if event.type != evdev.ecodes.EV_SYN:
                with _input_lock:
                    _last_input_time = time.monotonic()
    except PermissionError:
        logging.warning("アクセス拒否: %s — inputグループを確認してください", path)
    except Exception as exc:
        logging.warning("デバイス監視エラー (%s): %s", path, exc)


def start_input_watchers() -> None:
    for path in _physical_devices():
        threading.Thread(target=_watch_device, args=(path,), daemon=True).start()


def get_idle_ms() -> int:
    with _input_lock:
        return int((time.monotonic() - _last_input_time) * 1000)
