from collections.abc import Iterator
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
            status_text="Remaining 49:55",
            today_text="Today 3h 25m",
            paused=False,
            bgm_muted=False,
            bgm_volume=50,
        )

        self.popup.show()
        self.popup.refresh(
            status_text="Remaining 49:54",
            today_text="Today 3h 25m",
            paused=False,
            bgm_muted=False,
            bgm_volume=50,
        )

        self.assertEqual(self.popup.window.state(), "normal")
        self.assertEqual(
            self.popup.status_label.cget("text"),
            "Remaining 49:54",
        )
        self.assertEqual(self.popup.today_label.cget("text"), "Today 3h 25m")

    def test_停止とBGM設定を表示へ反映する(self) -> None:
        self.popup.refresh(
            status_text="Paused",
            today_text="Today 1h 10m",
            paused=True,
            bgm_muted=True,
            bgm_volume=70,
        )

        self.assertEqual(self.popup.pause_button.cget("text"), "Resume")
        self.assertTrue(self.popup.bgm_muted_var.get())
        self.assertEqual(self.popup.volume_label.cget("text"), "Volume: 70%")

    def test_項目を展開しても表示位置がずれない(self) -> None:
        self.popup.show()
        self.popup._anchor_x = self.popup.window.winfo_screenwidth() // 2
        self.popup._anchor_y = self.popup.window.winfo_screenheight() // 2
        self.popup.window.update_idletasks()
        self.popup._move_near_anchor()
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
            "Reset": "reset",
            "Pause": "pause",
            "Restart": "restart",
            "Mute": "mute",
            "Volume Up": "volume_up",
            "Volume Down": "volume_down",
            "Next Track": "next_track",
            "Quit": "quit",
        }
        buttons = {
            str(widget.cget("text")): widget
            for widget in self._descendants(self.popup.container)
            if isinstance(widget, (tk.Button, tk.Checkbutton))
            and widget.cget("text") in expected_actions
        }

        self.assertEqual(set(buttons), set(expected_actions))
        for button in buttons.values():
            button.invoke()

        self.assertCountEqual(self.actions, expected_actions.values())

    def _descendants(self, widget: tk.Misc) -> Iterator[tk.Misc]:
        for child in widget.winfo_children():
            yield child
            yield from self._descendants(child)


if __name__ == "__main__":
    unittest.main()
