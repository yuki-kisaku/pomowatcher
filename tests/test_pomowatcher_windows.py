import queue
import unittest
from unittest.mock import Mock, patch

from pomowatcher_app.settings import AppSettings
from pomowatcher_app.timer import PomodoroTimer, TimerState
from pomowatcher_app.windows import app as windows_app
from pomowatcher_app.windows import tray as windows_tray


class FakeRoot:
    def __init__(self) -> None:
        self.withdrawn = False

    def withdraw(self) -> None:
        self.withdrawn = True


class FakeVariable:
    def __init__(self, *, master: object, value: object) -> None:
        self.master = master
        self.value = value

    def set(self, value: object) -> None:
        self.value = value


class FakeMenu:
    def __init__(self, _parent: object, *, tearoff: bool) -> None:
        self.tearoff = tearoff
        self.entries: list[dict[str, object]] = []

    def add_command(self, **options: object) -> None:
        self.entries.append({"type": "command", **options})

    def add_checkbutton(self, **options: object) -> None:
        self.entries.append({"type": "checkbutton", **options})

    def add_cascade(self, **options: object) -> None:
        self.entries.append({"type": "cascade", **options})

    def add_separator(self) -> None:
        self.entries.append({"type": "separator"})

    def entryconfigure(self, index: int, **options: object) -> None:
        self.entries[index].update(options)


class PomowatcherWindowsAppTest(unittest.TestCase):
    def make_menu_app(self) -> windows_app.PomowatcherWindowsApp:
        app = windows_app.PomowatcherWindowsApp.__new__(windows_app.PomowatcherWindowsApp)
        app.timer = PomodoroTimer(
            work_threshold_sec=3_000,
            break_threshold_sec=600,
            active_limit_ms=30_000,
            now=0,
        )
        app.controller = Mock()
        app.controller.settings = AppSettings(bgm_muted=False, bgm_volume=50)
        app.actions = queue.SimpleQueue()
        app.root = FakeRoot()
        return app

    def build_menu(self, app: windows_app.PomowatcherWindowsApp) -> FakeMenu:
        with (
            patch.object(windows_app.tk, "Menu", side_effect=FakeMenu),
            patch.object(windows_app.tk, "BooleanVar", side_effect=FakeVariable),
        ):
            return app._build_tray_menu()

    @patch.object(windows_app.threading, "Thread", return_value=Mock())
    @patch.object(windows_app, "WindowsMediaMonitor", return_value=Mock())
    @patch.object(windows_app, "WindowsTrayIcon", return_value=Mock())
    @patch.object(windows_app, "WindowsNotifier", return_value=Mock())
    @patch.object(windows_app, "MpvBgmPlayer", return_value=Mock())
    @patch.object(windows_app, "WindowsMpvAdapter", return_value=Mock())
    @patch.object(windows_app, "SettingsStore")
    @patch.object(windows_app.tk, "BooleanVar", return_value=Mock())
    @patch.object(windows_app.tk, "Menu", return_value=Mock())
    def test_起動時にタイマー小窓を表示しない(
        self,
        _menu: Mock,
        _boolean_var: Mock,
        settings_store: Mock,
        _mpv_adapter: Mock,
        _bgm_player: Mock,
        _notifier: Mock,
        _tray_icon: Mock,
        _media_monitor: Mock,
        _thread: Mock,
    ) -> None:
        settings_store.return_value.load.return_value = AppSettings()
        root = FakeRoot()
        with patch.object(windows_app.tk, "Tk", return_value=root):
            windows_app.PomowatcherWindowsApp(Mock())
        self.assertTrue(root.withdrawn)

    def test_トレイメニューからタイマーを操作できる(self) -> None:
        app = self.make_menu_app()
        menu = self.build_menu(app)
        pomodoro_menu = menu.entries[2]["menu"]
        self.assertIsInstance(pomodoro_menu, FakeMenu)
        self.assertEqual(
            [entry.get("label") for entry in pomodoro_menu.entries],
            ["リセット", "停止", "再起動"],
        )
        app.timer.paused = True
        app.tray_menu = menu
        app.tray = Mock()
        app._last_icon_key = None
        app._refresh_view()
        self.assertEqual(pomodoro_menu.entries[1]["label"], "再開")

    def test_トレイの説明に正確な残り時間を表示する(self) -> None:
        app = self.make_menu_app()
        app.timer.update(idle_ms=0, now=1)
        app.timer.update(idle_ms=0, now=6)
        self.assertEqual(app._tray_status_text(), "Pomowatcher — 残り 49:55")

    def test_開いているメニューの残り時間を更新する(self) -> None:
        app = self.make_menu_app()
        menu = self.build_menu(app)
        app.tray_menu = menu
        app.tray = Mock()
        app._last_icon_key = None
        app.timer.update(idle_ms=0, now=1)
        app.timer.update(idle_ms=0, now=6)

        app._refresh_view()
        self.assertEqual(menu.entries[0]["label"], "Pomowatcher — 残り 49:55")

        app.timer.update(idle_ms=0, now=7)
        app._refresh_view()
        self.assertEqual(menu.entries[0]["label"], "Pomowatcher — 残り 49:54")

    def test_トレイの進捗円は本家と同じ5段階で埋まる(self) -> None:
        progress_pixel_counts = []
        progress_color = (62, 156, 255, 255)
        for progress_index in range(5):
            icon = windows_tray.render_tray_icon(TimerState.WORKING, progress_index)
            progress_pixel_counts.append(
                sum(
                    icon.getpixel((x, y)) == progress_color
                    for y in range(icon.height)
                    for x in range(icon.width)
                )
            )
        self.assertEqual(progress_pixel_counts[0], 0)
        self.assertTrue(
            all(
                previous < current
                for previous, current in zip(
                    progress_pixel_counts,
                    progress_pixel_counts[1:],
                )
            )
        )

    def test_左クリックでトレイメニューを開く(self) -> None:
        icon = windows_tray.WindowsTrayIcon.__new__(windows_tray.WindowsTrayIcon)
        icon._running = False
        icon._icon_handle = None
        icon._on_menu_requested = Mock()
        with patch.object(windows_tray.pystray.Icon, "_on_notify") as notify:
            icon._on_notify(0, windows_tray.pystray_win32.WM_LBUTTONUP)
        icon._on_menu_requested.assert_called_once_with()
        notify.assert_not_called()

    def test_右クリックでもトレイメニューを開く(self) -> None:
        icon = windows_tray.WindowsTrayIcon.__new__(windows_tray.WindowsTrayIcon)
        icon._running = False
        icon._icon_handle = None
        icon._on_menu_requested = Mock()
        with patch.object(windows_tray.pystray.Icon, "_on_notify") as notify:
            icon._on_notify(0, windows_tray.pystray_win32.WM_RBUTTONUP)
        icon._on_menu_requested.assert_called_once_with()
        notify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
