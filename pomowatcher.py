#!/usr/bin/env python3
import atexit
import json
import os
import socket
import subprocess
import logging
import sys
import time
import threading

import evdev
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import Gtk, GLib, Gio, AyatanaAppIndicator3 as AppIndicator3

# --- 設定 ---
WORK_THRESHOLD_SEC  = 50 * 60
IDLE_THRESHOLD_SEC  = 10 * 60
CHECK_INTERVAL_SEC  = 30
ACTIVE_LIMIT_MS     = 30 * 1000

# 作業中 BGM
# 優先順:
#   1. ~/Music/pomodoro-bgm/ ディレクトリ → 中の全曲をシャッフル再生
#   2. ~/Music/pomodoro-bgm.mp3 など単一ファイル → ループ再生
# いずれも存在しない場合は何も再生しない
BGM_DIR = os.path.expanduser("~/Music/pomodoro-bgm")
BGM_FILE_CANDIDATES = [
    f"{BGM_DIR}.mp3",
    f"{BGM_DIR}.ogg",
    f"{BGM_DIR}.flac",
    f"{BGM_DIR}.m4a",
    f"{BGM_DIR}.opus",
    f"{BGM_DIR}.webm",
]
AUDIO_EXTENSIONS = {".mp3", ".ogg", ".flac", ".m4a", ".opus", ".webm", ".wav", ".aac"}
MPV_IPC_PATH = f"/tmp/pomowatcher-mpv-{os.getuid()}.sock"
SETTINGS_DIR = os.path.expanduser("~/.config/pomowatcher")
SETTINGS_PATH = os.path.join(SETTINGS_DIR, "settings.json")
BGM_VOLUME_DEFAULT = 50
BGM_VOLUME_MIN = 0
BGM_VOLUME_MAX = 125
BGM_VOLUME_STEP = 10
BLANK_ICON_NAME = "pomowatcher-blank"
BLANK_ICON_DIR = os.path.expanduser("~/.cache/pomowatcher")
BLANK_ICON_PATH = os.path.join(BLANK_ICON_DIR, f"{BLANK_ICON_NAME}.svg")

logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                    format="%(asctime)s %(message)s", datefmt="%H:%M:%S")


def _ensure_blank_icon():
    os.makedirs(BLANK_ICON_DIR, exist_ok=True)
    if not os.path.exists(BLANK_ICON_PATH):
        with open(BLANK_ICON_PATH, "w", encoding="utf-8") as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>\n')
    return BLANK_ICON_NAME


# --- 設定ファイル ---

def _normalize_bgm_volume(value):
    try:
        volume = int(value)
    except (TypeError, ValueError):
        return BGM_VOLUME_DEFAULT
    if volume < BGM_VOLUME_MIN or volume > BGM_VOLUME_MAX:
        return BGM_VOLUME_DEFAULT
    return volume


def _load_settings():
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, OSError, json.JSONDecodeError) as e:
        if not isinstance(e, FileNotFoundError):
            logging.warning(f"設定を読み込めません。初期値で続行します: {e}")
        return {"bgm_muted": False, "bgm_volume": BGM_VOLUME_DEFAULT}

    return {
        "bgm_muted": data.get("bgm_muted") is True,
        "bgm_volume": _normalize_bgm_volume(data.get("bgm_volume")),
    }


def _save_settings(settings):
    try:
        os.makedirs(SETTINGS_DIR, exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "bgm_muted": settings["bgm_muted"] is True,
                    "bgm_volume": _normalize_bgm_volume(settings.get("bgm_volume")),
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
            f.write("\n")
    except OSError as e:
        logging.warning(f"設定を保存できません: {e}")


# --- BGM 管理 ---

_bgm_process = None
_bgm_paused_by_idle = False
_bgm_paused_by_mpris = False
_bgm_paused_by_mute = False
_bgm_paused_by_app = False
_bgm_muted = False
_bgm_volume = BGM_VOLUME_DEFAULT
_mpris_playing = False
_bgm_lock = threading.Lock()


def _find_bgm_target():
    """BGM の再生対象を返す。
    - ディレクトリが存在すれば "dir:/path"
    - 単一ファイルがあれば "file:/path"
    - なければ None
    """
    if os.path.isdir(BGM_DIR):
        audio_files = sorted(
            f for f in os.listdir(BGM_DIR)
            if os.path.splitext(f)[1].lower() in AUDIO_EXTENSIONS
        )
        if audio_files:
            return ("dir", BGM_DIR)
    for path in BGM_FILE_CANDIDATES:
        if os.path.isfile(path):
            return ("file", path)
    return None


def _start_bgm():
    """mpv を起動する。すでに再生中なら何もしない。"""
    global _bgm_process, _bgm_paused_by_idle, _bgm_paused_by_mpris
    global _bgm_paused_by_mute, _bgm_paused_by_app
    with _bgm_lock:
        if _bgm_muted or _mpris_playing:
            return
        volume = _bgm_volume
    target = _find_bgm_target()
    if target is None:
        logging.debug(f"BGM が見つかりません: {BGM_DIR}")
        return
    kind, path = target
    with _bgm_lock:
        if _bgm_process is not None and _bgm_process.poll() is None:
            return
        try:
            try:
                os.unlink(MPV_IPC_PATH)
            except FileNotFoundError:
                pass
            if kind == "dir":
                cmd = [
                    "mpv",
                    "--no-video",
                    "--shuffle",
                    "--loop-playlist=inf",
                    f"--volume={volume}",
                    f"--input-ipc-server={MPV_IPC_PATH}",
                    "--really-quiet",
                    path,
                ]
            else:
                cmd = [
                    "mpv",
                    "--no-video",
                    "--loop-file=inf",
                    f"--volume={volume}",
                    f"--input-ipc-server={MPV_IPC_PATH}",
                    "--really-quiet",
                    path,
                ]
            _bgm_process = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            _bgm_paused_by_idle = False
            _bgm_paused_by_mpris = False
            _bgm_paused_by_mute = False
            _bgm_paused_by_app = False
            logging.info(f"BGM 再生開始: {path} ({kind})")
        except FileNotFoundError:
            logging.warning("mpv が見つかりません。sudo apt install mpv でインストールしてください")


def _send_mpv_command(command):
    """再生中の mpv に IPC コマンドを送る。"""
    payload = json.dumps({"command": command}).encode("utf-8") + b"\n"
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(1)
            client.connect(MPV_IPC_PATH)
            client.sendall(payload)
        return True
    except (FileNotFoundError, ConnectionRefusedError, OSError) as e:
        logging.warning(f"mpv 操作に失敗しました: {e}")
        return False


def _is_bgm_running():
    return _bgm_process is not None and _bgm_process.poll() is None


def _is_bgm_paused_by_idle():
    with _bgm_lock:
        return _bgm_paused_by_idle and _is_bgm_running()


def _pause_bgm(reason):
    """mpv を終了せず、曲位置を保って一時停止する。"""
    global _bgm_paused_by_idle, _bgm_paused_by_mpris
    global _bgm_paused_by_mute, _bgm_paused_by_app
    with _bgm_lock:
        if reason == "idle" and _bgm_paused_by_idle:
            return False
        if reason == "mpris" and _bgm_paused_by_mpris:
            return False
        if reason == "mute" and _bgm_paused_by_mute:
            return False
        if reason == "app" and _bgm_paused_by_app:
            return False
        if not _is_bgm_running():
            return False

        already_paused = (
            _bgm_paused_by_idle
            or _bgm_paused_by_mpris
            or _bgm_paused_by_mute
            or _bgm_paused_by_app
        )

    if not already_paused:
        if not _send_mpv_command(["set_property", "pause", True]):
            return False

    with _bgm_lock:
        if _is_bgm_running():
            if reason == "idle":
                _bgm_paused_by_idle = True
                logging.info("BGM 一時停止（idle）")
            elif reason == "mpris":
                _bgm_paused_by_mpris = True
                logging.info("BGM 一時停止（他メディア再生中）")
            elif reason == "mute":
                _bgm_paused_by_mute = True
                logging.info("BGM 一時停止（ミュート）")
            elif reason == "app":
                _bgm_paused_by_app = True
                logging.info("BGM 一時停止（アプリ停止）")
            return True
    return False


def _release_bgm_pause(reason):
    """指定した理由の一時停止を解除し、他に止める理由がなければ再開する。"""
    global _bgm_paused_by_idle, _bgm_paused_by_mpris
    global _bgm_paused_by_mute, _bgm_paused_by_app
    with _bgm_lock:
        if reason == "idle":
            if not _bgm_paused_by_idle:
                return False
            _bgm_paused_by_idle = False
        elif reason == "mpris":
            if not _bgm_paused_by_mpris:
                return False
            _bgm_paused_by_mpris = False
        elif reason == "mute":
            if not _bgm_paused_by_mute:
                return False
            _bgm_paused_by_mute = False
        elif reason == "app":
            if not _bgm_paused_by_app:
                return False
            _bgm_paused_by_app = False
        else:
            return False

        should_resume = (
            _is_bgm_running()
            and not _bgm_paused_by_idle
            and not _bgm_paused_by_mpris
            and not _bgm_paused_by_mute
            and not _bgm_paused_by_app
            and not _bgm_muted
            and not _mpris_playing
        )
        if not should_resume:
            return False

    if not _send_mpv_command(["set_property", "pause", False]):
        return False

    logging.info("BGM 再開")
    return True


def _next_bgm_track():
    """シャッフル再生中の次の曲へ送る。"""
    with _bgm_lock:
        if _bgm_muted or _mpris_playing:
            return False
        if _bgm_process is None or _bgm_process.poll() is not None:
            return False
    _send_mpv_command(["playlist-next", "weak"])
    logging.info("BGM 次の曲")
    return True


def _stop_bgm():
    """再生中の mpv を停止する。"""
    global _bgm_process, _bgm_paused_by_idle, _bgm_paused_by_mpris
    global _bgm_paused_by_mute, _bgm_paused_by_app
    with _bgm_lock:
        p = _bgm_process
        _bgm_process = None
        _bgm_paused_by_idle = False
        _bgm_paused_by_mpris = False
        _bgm_paused_by_mute = False
        _bgm_paused_by_app = False

    if p is None:
        return

    try:
        p.terminate()
        p.wait(timeout=2)
    except (subprocess.TimeoutExpired, ProcessLookupError):
        try:
            p.kill()
            p.wait(timeout=2)
        except (subprocess.TimeoutExpired, ProcessLookupError):
            pass
    try:
        os.unlink(MPV_IPC_PATH)
    except FileNotFoundError:
        pass
    logging.info("BGM 停止")


def _set_bgm_muted(muted):
    global _bgm_muted
    with _bgm_lock:
        _bgm_muted = muted
    if muted:
        _pause_bgm("mute")
    else:
        _release_bgm_pause("mute")


def _set_bgm_volume(volume):
    global _bgm_volume
    volume = _normalize_bgm_volume(volume)
    with _bgm_lock:
        _bgm_volume = volume
        running = _is_bgm_running()
    if running:
        _send_mpv_command(["set_property", "volume", volume])
    logging.info(f"BGM 音量 {volume}%")
    return volume


def _set_mpris_playing(playing):
    global _mpris_playing
    with _bgm_lock:
        _mpris_playing = playing


atexit.register(_stop_bgm)


# --- MPRIS 監視 ---

MPRIS_PREFIX = "org.mpris.MediaPlayer2."
MPRIS_PLAYER_PATH = "/org/mpris/MediaPlayer2"
MPRIS_PLAYER_INTERFACE = "org.mpris.MediaPlayer2.Player"

_session_bus = None
_mpris_warned = False


def _get_session_bus():
    global _session_bus, _mpris_warned
    if _session_bus is not None:
        return _session_bus
    try:
        _session_bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        return _session_bus
    except GLib.Error as e:
        if not _mpris_warned:
            logging.warning(f"MPRIS を確認できません。BGM連動なしで続行します: {e}")
            _mpris_warned = True
        return None


def _dbus_call(bus, name, path, interface, method, params, result_type):
    return bus.call_sync(
        name,
        path,
        interface,
        method,
        params,
        GLib.VariantType.new(result_type) if result_type else None,
        Gio.DBusCallFlags.NONE,
        1000,
        None,
    )


def _dbus_name_pid(bus, name):
    try:
        result = _dbus_call(
            bus,
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "GetConnectionUnixProcessID",
            GLib.Variant("(s)", (name,)),
            "(u)",
        )
        return result.unpack()[0]
    except GLib.Error:
        return None


def _is_own_bgm_player(bus, name):
    with _bgm_lock:
        if _bgm_process is None or _bgm_process.poll() is not None:
            return False
        bgm_pid = _bgm_process.pid
    return _dbus_name_pid(bus, name) == bgm_pid


def _is_mpris_playing():
    bus = _get_session_bus()
    if bus is None:
        return False

    try:
        result = _dbus_call(
            bus,
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "ListNames",
            None,
            "(as)",
        )
        names = result.unpack()[0]
    except GLib.Error as e:
        logging.warning(f"MPRIS プレイヤー一覧を読めません: {e}")
        return False

    for name in names:
        if not name.startswith(MPRIS_PREFIX):
            continue
        if _is_own_bgm_player(bus, name):
            continue

        try:
            result = _dbus_call(
                bus,
                name,
                MPRIS_PLAYER_PATH,
                "org.freedesktop.DBus.Properties",
                "Get",
                GLib.Variant("(ss)", (MPRIS_PLAYER_INTERFACE, "PlaybackStatus")),
                "(v)",
            )
            status = result.get_child_value(0).get_variant().unpack()
        except GLib.Error:
            continue

        if status == "Playing":
            return True

    return False


# --- 拡張ポイント ---

def on_work_start():
    if not _release_bgm_pause("idle"):
        _start_bgm()

def on_break_detected():
    _stop_bgm()

def on_50min_reached():
    _stop_bgm()
    subprocess.run([
        "notify-send", "--urgency=normal",
        "作業50分経過", "そろそろ休憩しましょう！",
    ])
    try:
        subprocess.run([
            "canberra-gtk-play",
            "-f", "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga",
        ], check=False)
    except FileNotFoundError:
        logging.warning("効果音を再生できません: canberra-gtk-play が見つかりません")


# --- 物理デバイス監視によるアイドル検知 ---

_last_input_time = time.monotonic()
_input_lock = threading.Lock()


def _physical_devices():
    """キーボード・マウス相当の物理デバイスのパスを返す。
    keyd の仮想キーボードは許可し、仮想ポインタやオーディオ SW デバイスは除外する。
    """
    EV_KEY = 1 << 1
    EV_REL = 1 << 2

    devices = []
    current_name = ""
    current_phys = None
    current_handlers = []
    current_ev = 0
    for line in open("/proc/bus/input/devices"):
        line = line.strip()
        if line.startswith("N:"):
            current_name = line.split("=", 1)[1].strip().strip('"')
        elif line.startswith("P:"):
            current_phys = line.split("=", 1)[1].strip()
        elif line.startswith("H:"):
            current_handlers = line.split("=", 1)[1].split()
        elif line.startswith("B:") and "EV=" in line:
            current_ev = int(line.split("=")[1], 16)
        elif line == "":
            is_keyd_keyboard = current_name == "keyd virtual keyboard"
            if (current_phys or is_keyd_keyboard) and (current_ev & (EV_KEY | EV_REL)):
                for h in current_handlers:
                    if h.startswith("event"):
                        devices.append(f"/dev/input/{h}")
            current_name = ""
            current_phys = None
            current_handlers = []
            current_ev = 0
    return devices


def _watch_device(path: str):
    global _last_input_time
    try:
        dev = evdev.InputDevice(path)
        logging.info(f"監視開始: {dev.name} ({path})")
        for event in dev.read_loop():
            if event.type != evdev.ecodes.EV_SYN:
                with _input_lock:
                    _last_input_time = time.monotonic()
    except PermissionError:
        logging.warning(f"アクセス拒否: {path} — input グループに追加されているか確認してください")
    except Exception as e:
        logging.warning(f"デバイス監視エラー ({path}): {e}")


def start_input_watchers():
    for path in _physical_devices():
        t = threading.Thread(target=_watch_device, args=(path,), daemon=True)
        t.start()


def get_idle_ms() -> int:
    with _input_lock:
        return int((time.monotonic() - _last_input_time) * 1000)


# --- メインクラス ---

class PomoWatcher:
    def __init__(self):
        self.settings = _load_settings()
        _set_bgm_muted(self.settings["bgm_muted"])
        _set_bgm_volume(self.settings["bgm_volume"])

        self.active_seconds = 0
        self.paused = False
        self.mpris_playing = False
        self.was_on_break = True
        self.awaiting_break = False  # 50分到達後、10分アイドルになるまで True
        self.window_start = None  # 現在のウィンドウの開始時刻（monotonic）

        self.indicator = self._build_indicator()

        GLib.timeout_add(100, self._refresh_mpris_once)  # 起動直後に他メディア再生を確認
        GLib.timeout_add(500, self._tick_once)  # 起動0.5秒後に1回だけ実行
        GLib.timeout_add_seconds(CHECK_INTERVAL_SEC, self._tick)
        GLib.timeout_add_seconds(1, self._refresh_indicator)
        GLib.timeout_add_seconds(2, self._refresh_mpris)
        logging.info("pomowatcher 開始")

    # --- トレイアイコン ---

    def _build_indicator(self):
        icon_name = _ensure_blank_icon()
        indicator = AppIndicator3.Indicator.new(
            "pomowatcher",
            icon_name,
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        indicator.set_icon_theme_path(BLANK_ICON_DIR)
        indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        indicator.set_label(f"○ {WORK_THRESHOLD_SEC // 60}:00", f"○ {WORK_THRESHOLD_SEC // 60}:00")

        menu = Gtk.Menu()

        reset_item = Gtk.MenuItem(label="リセット")
        reset_item.connect("activate", self._on_reset)
        menu.append(reset_item)

        self.pause_menu_item = Gtk.MenuItem(label="停止")
        self.pause_menu_item.connect("activate", self._on_pause_toggle)
        menu.append(self.pause_menu_item)

        bgm_item = Gtk.MenuItem(label="BGM")
        bgm_menu = Gtk.Menu()
        bgm_item.set_submenu(bgm_menu)
        menu.append(bgm_item)

        self.bgm_mute_menu_item = Gtk.CheckMenuItem(label="ミュート")
        self.bgm_mute_menu_item.set_active(self.settings["bgm_muted"])
        self.bgm_mute_menu_item.connect("toggled", self._on_bgm_mute_toggle)
        bgm_menu.append(self.bgm_mute_menu_item)

        bgm_menu.append(Gtk.SeparatorMenuItem())

        self.bgm_volume_label_item = Gtk.MenuItem(label="")
        self.bgm_volume_label_item.set_sensitive(False)
        bgm_menu.append(self.bgm_volume_label_item)

        volume_up_item = Gtk.MenuItem(label="音量を上げる")
        volume_up_item.connect("activate", self._on_bgm_volume_up)
        bgm_menu.append(volume_up_item)

        volume_down_item = Gtk.MenuItem(label="音量を下げる")
        volume_down_item.connect("activate", self._on_bgm_volume_down)
        bgm_menu.append(volume_down_item)

        bgm_menu.append(Gtk.SeparatorMenuItem())

        next_track_item = Gtk.MenuItem(label="次の曲")
        next_track_item.connect("activate", self._on_next_track)
        bgm_menu.append(next_track_item)

        quit_item = Gtk.MenuItem(label="終了")
        quit_item.connect("activate", self._on_quit)
        menu.append(quit_item)

        menu.show_all()
        self._update_bgm_volume_label()
        indicator.set_menu(menu)
        return indicator

    def _on_quit(self, *_):
        _stop_bgm()
        Gtk.main_quit()

    def _progress_icon(self) -> str:
        icons = ["○", "◔", "◑", "◕", "●"]
        ratio = min(1.0, self.active_seconds / WORK_THRESHOLD_SEC)
        return icons[int(ratio * (len(icons) - 1))]

    def _update_indicator(self):
        if self.paused:
            self.indicator.set_label("❚❚ Paused", "❚❚ Paused")
            return
        if self.awaiting_break:
            self.indicator.set_label("Take a break!!", "Take a break!!")
            return
        elapsed = self._display_elapsed()
        remaining = max(0, WORK_THRESHOLD_SEC - elapsed)
        mins, secs = divmod(int(remaining), 60)
        label = f"{self._progress_icon()} {mins:02d}:{secs:02d}"
        self.indicator.set_label(label, label)

    # --- タイマー ---

    def _refresh_indicator(self) -> bool:
        if (
            not self.paused
            and not self.awaiting_break
            and not self.was_on_break
            and _is_bgm_paused_by_idle()
            and get_idle_ms() <= ACTIVE_LIMIT_MS
        ):
            logging.info("作業再開を検知（BGM 即時再開）")
            on_work_start()

        if (
            self.was_on_break
            and not self.paused
            and not self.awaiting_break
            and get_idle_ms() <= ACTIVE_LIMIT_MS
        ):
            logging.info("作業再開を検知（即時）")
            on_work_start()
            self.was_on_break = False
            self.window_start = time.monotonic()
        self._update_indicator()
        return True

    def _should_play_bgm_now(self):
        return not self.paused and not self.awaiting_break and not self.was_on_break

    def _refresh_mpris(self) -> bool:
        playing = _is_mpris_playing()
        if playing == self.mpris_playing:
            return True

        self.mpris_playing = playing
        _set_mpris_playing(playing)

        if playing:
            _pause_bgm("mpris")
            logging.info("他メディアの再生を検知")
        else:
            logging.info("他メディアの再生終了を検知")
            if not _release_bgm_pause("mpris") and self._should_play_bgm_now():
                _start_bgm()

        return True

    def _refresh_mpris_once(self) -> bool:
        self._refresh_mpris()
        return False

    def _display_elapsed(self) -> float:
        """コミット済み時間 + 現ウィンドウの経過秒を合計した表示用の経過時間"""
        elapsed = self.active_seconds
        if self.window_start is not None and not self.paused and not self.was_on_break:
            elapsed += min(time.monotonic() - self.window_start, CHECK_INTERVAL_SEC)
        return elapsed

    # --- メニューハンドラ ---

    def _on_reset(self, *_):
        self.active_seconds = 0
        self.window_start = time.monotonic()
        self.was_on_break = False
        self.awaiting_break = False
        self.pause_menu_item.set_label("停止")
        self._update_indicator()
        on_work_start()  # リセット後は作業開始扱い
        logging.info("リセット")

    def _on_pause_toggle(self, *_):
        self.paused = not self.paused
        self.pause_menu_item.set_label("再開" if self.paused else "停止")
        if self.paused:
            _pause_bgm("app")
        else:
            # 再開時：休憩中でなければ BGM 再開
            if not self.awaiting_break and not self.was_on_break:
                if not _release_bgm_pause("app"):
                    _start_bgm()
        logging.info("一時停止" if self.paused else "再開")
        self._update_indicator()

    def _on_bgm_mute_toggle(self, item):
        muted = item.get_active()
        self.settings["bgm_muted"] = muted
        _set_bgm_muted(muted)
        _save_settings(self.settings)
        logging.info("BGM ミュート ON" if muted else "BGM ミュート OFF")
        if not muted and self._should_play_bgm_now():
            _start_bgm()

    def _update_bgm_volume_label(self):
        self.bgm_volume_label_item.set_label(f"音量: {self.settings['bgm_volume']}%")

    def _change_bgm_volume(self, delta):
        current = self.settings["bgm_volume"]
        volume = max(BGM_VOLUME_MIN, min(BGM_VOLUME_MAX, current + delta))
        volume = _set_bgm_volume(volume)
        self.settings["bgm_volume"] = volume
        _save_settings(self.settings)
        self._update_bgm_volume_label()

    def _on_bgm_volume_up(self, *_):
        self._change_bgm_volume(BGM_VOLUME_STEP)

    def _on_bgm_volume_down(self, *_):
        self._change_bgm_volume(-BGM_VOLUME_STEP)

    def _on_next_track(self, *_):
        if _next_bgm_track():
            return
        if not self.paused and not self.awaiting_break and not self.was_on_break:
            _start_bgm()

    # --- 定期チェック ---

    def _tick(self) -> bool:
        if self.paused:
            return True

        idle_ms = get_idle_ms()
        is_idle = idle_ms > ACTIVE_LIMIT_MS
        idle_sec = idle_ms // 1000
        logging.info(f"idle_ms={idle_ms}, is_idle={is_idle}")

        if self.awaiting_break:
            if idle_sec >= IDLE_THRESHOLD_SEC:
                logging.info(f"休憩完了（{idle_sec // 60}分{idle_sec % 60}秒アイドル）")
                on_break_detected()
                self.active_seconds = 0
                self.was_on_break = True
                self.awaiting_break = False
            self._update_indicator()
            return True

        if not is_idle:
            if self.was_on_break:
                logging.info("作業再開を検知")
                on_work_start()
                self.was_on_break = False
            elif _is_bgm_paused_by_idle():
                on_work_start()

            self.active_seconds += CHECK_INTERVAL_SEC
            self.window_start = time.monotonic()
            logging.info(f"作業中 ... {self.active_seconds // 60}分{self.active_seconds % 60}秒経過")

            if self.active_seconds >= WORK_THRESHOLD_SEC:
                logging.info("50分到達！通知送信")
                on_50min_reached()
                self.awaiting_break = True

        else:
            _pause_bgm("idle")
            if idle_sec >= IDLE_THRESHOLD_SEC and not self.was_on_break:
                logging.info(f"休憩検知（{idle_sec // 60}分{idle_sec % 60}秒アイドル）→ リセット")
                on_break_detected()
                self.active_seconds = 0
                self.was_on_break = True

        self._update_indicator()

        return True

    def _tick_once(self) -> bool:
        self._tick()
        return False  # 繰り返さない

    def run(self):
        Gtk.main()


if __name__ == "__main__":
    start_input_watchers()
    app = PomoWatcher()
    app.run()
