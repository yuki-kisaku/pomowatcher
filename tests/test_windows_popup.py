import tkinter as tk
import unittest

from pomowatcher_app.windows.popup import TrayPopup


class TrayPopupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tk.Tk()
        self.root.withdraw()
        self.actions: list[str] = []
        self.popup = TrayPopup(self.root, self.actions.append)

    def tearDown(self) -> None:
        self.root.destroy()

    def test_表示したまま残り時間を更新できる(self) -> None:
        self.popup.refresh(
            status_text="Pomowatcher — 残り 49:55",
            paused=False,
            bgm_muted=False,
            bgm_volume=50,
        )

        self.popup.show()
        self.popup.refresh(
            status_text="Pomowatcher — 残り 49:54",
            paused=False,
            bgm_muted=False,
            bgm_volume=50,
        )

        self.assertEqual(self.popup.window.state(), "normal")
        self.assertEqual(
            self.popup.status_label.cget("text"),
            "Pomowatcher — 残り 49:54",
        )

    def test_停止とBGM設定を表示へ反映する(self) -> None:
        self.popup.refresh(
            status_text="Pomowatcher — 停止中",
            paused=True,
            bgm_muted=True,
            bgm_volume=70,
        )

        self.assertEqual(self.popup.pause_button.cget("text"), "再開")
        self.assertTrue(self.popup.bgm_muted_var.get())
        self.assertEqual(self.popup.volume_label.cget("text"), "音量: 70%")

    def test_項目を展開しても表示位置がずれない(self) -> None:
        self.popup.show()
        self.popup.window.update_idletasks()
        initial_anchor = (
            self.popup.window.winfo_x() + self.popup.window.winfo_width(),
            self.popup.window.winfo_y() + self.popup.window.winfo_height(),
        )

        self.popup.pomodoro_button.invoke()
        self.popup.window.update_idletasks()
        expanded_anchor = (
            self.popup.window.winfo_x() + self.popup.window.winfo_width(),
            self.popup.window.winfo_y() + self.popup.window.winfo_height(),
        )

        self.assertEqual(expanded_anchor, initial_anchor)

    def test_既存の操作をすべて実行できる(self) -> None:
        expected_actions = {
            "reset",
            "pause",
            "restart",
            "mute",
            "volume_up",
            "volume_down",
            "next_track",
            "quit",
        }

        self.assertEqual(set(self.popup.action_buttons), expected_actions)
        for action in expected_actions:
            self.popup.action_buttons[action].invoke()

        self.assertCountEqual(self.actions, expected_actions)


if __name__ == "__main__":
    unittest.main()
