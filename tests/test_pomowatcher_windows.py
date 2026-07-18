import queue
import unittest
from unittest.mock import Mock, patch

import pomowatcher_windows


class FakeRoot:
    def __init__(self) -> None:
        self.withdrawn = False

    def withdraw(self) -> None:
        self.withdrawn = True


class PomowatcherWindowsAppTest(unittest.TestCase):
    def make_menu_app(self) -> pomowatcher_windows.PomowatcherWindowsApp:
        app = pomowatcher_windows.PomowatcherWindowsApp.__new__(
            pomowatcher_windows.PomowatcherWindowsApp
        )
        app.timer = pomowatcher_windows.PomodoroTimer(
            work_threshold_sec=3_000,
            break_threshold_sec=600,
            active_limit_ms=30_000,
            now=0,
        )
        app.settings = {"bgm_muted": False, "bgm_volume": 50}
        app.actions = queue.SimpleQueue()
        return app

    @patch.object(pomowatcher_windows.threading, "Thread", return_value=Mock())
    @patch.object(pomowatcher_windows, "WindowsTrayIcon", return_value=Mock())
    @patch.object(pomowatcher_windows, "WindowsNotifier", return_value=Mock())
    @patch.object(pomowatcher_windows, "MpvBgmPlayer", return_value=Mock())
    @patch.object(
        pomowatcher_windows,
        "_load_settings",
        return_value={"bgm_muted": False, "bgm_volume": 50},
    )
    def test_起動時にタイマー小窓を表示しない(
        self,
        _load_settings: Mock,
        _bgm_player: Mock,
        _notifier: Mock,
        _tray_icon: Mock,
        _thread: Mock,
    ) -> None:
        root = FakeRoot()

        with patch.object(pomowatcher_windows.tk, "Tk", return_value=root):
            pomowatcher_windows.PomowatcherWindowsApp(Mock())

        self.assertTrue(root.withdrawn)

    def test_トレイメニューからタイマーを操作できる(self) -> None:
        app = self.make_menu_app()

        menu = app._build_tray_menu()
        pomodoro_menu = menu.items[2].submenu

        self.assertIsNotNone(pomodoro_menu)
        self.assertEqual(
            [item.text for item in pomodoro_menu.items],
            ["リセット", "停止", "再起動"],
        )

        app.timer.paused = True
        self.assertEqual(pomodoro_menu.items[1].text, "再開")

    def test_トレイの説明に正確な残り時間を表示する(self) -> None:
        app = self.make_menu_app()
        app.timer.update(idle_ms=0, now=1)
        app.timer.update(idle_ms=0, now=6)

        self.assertEqual(app._tray_status_text(), "Pomowatcher — 残り 49:55")

    def test_トレイの進捗円は本家と同じ5段階で埋まる(self) -> None:
        progress_pixel_counts = []
        progress_color = (62, 156, 255, 255)

        for progress_index in range(5):
            icon = pomowatcher_windows.PomowatcherWindowsApp._render_tray_icon(
                pomowatcher_windows.TimerState.WORKING,
                progress_index,
            )
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
        icon = pomowatcher_windows.WindowsTrayIcon.__new__(
            pomowatcher_windows.WindowsTrayIcon
        )
        icon._running = False
        icon._icon_handle = None

        with patch.object(
            pomowatcher_windows.pystray.Icon,
            "_on_notify",
        ) as notify:
            icon._on_notify(0, pomowatcher_windows.pystray_win32.WM_LBUTTONUP)

        notify.assert_called_once_with(
            0,
            pomowatcher_windows.pystray_win32.WM_RBUTTONUP,
        )

    def test_右クリックでもトレイメニューを開く(self) -> None:
        icon = pomowatcher_windows.WindowsTrayIcon.__new__(
            pomowatcher_windows.WindowsTrayIcon
        )
        icon._running = False
        icon._icon_handle = None

        with patch.object(
            pomowatcher_windows.pystray.Icon,
            "_on_notify",
        ) as notify:
            icon._on_notify(0, pomowatcher_windows.pystray_win32.WM_RBUTTONUP)

        notify.assert_called_once_with(
            0,
            pomowatcher_windows.pystray_win32.WM_RBUTTONUP,
        )


if __name__ == "__main__":
    unittest.main()
