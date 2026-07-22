"""Windowsの通知領域から開く、リアルタイム更新可能な操作画面。"""

from __future__ import annotations

from collections.abc import Callable
import tkinter as tk


class TrayPopup:
    """Windows標準メニューに似せた、処理を止めない小さな操作画面。"""

    BACKGROUND = "#f5f5f5"
    BORDER = "#b8b8b8"
    HOVER = "#e5e5e5"
    TEXT = "#202020"
    DISABLED_TEXT = "#777777"
    FONT = ("Segoe UI", 9)
    WIDTH = 230

    def __init__(
        self,
        master: tk.Misc,
        on_action: Callable[[str], None],
    ) -> None:
        self._on_action = on_action
        self._anchor_x = 0
        self._anchor_y = 0
        self.window = tk.Toplevel(master)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.configure(background=self.BORDER)
        self.window.bind("<Escape>", lambda _event: self.hide())
        self.window.bind("<FocusOut>", self._on_focus_out)

        self.container = tk.Frame(self.window, background=self.BACKGROUND)
        self.container.pack(fill="both", expand=True, padx=1, pady=1)
        self.action_buttons: dict[str, tk.Button | tk.Checkbutton] = {}

        self.status_label = self._add_label("Pomowatcher — 残り 50:00")
        self._add_separator()

        self.pomodoro_button = self._add_button(
            "Pomodoro  ›",
            self._toggle_pomodoro,
        )
        self.pomodoro_panel = tk.Frame(
            self.container,
            background=self.BACKGROUND,
        )
        self._add_action_button(self.pomodoro_panel, "リセット", "reset")
        self.pause_button = self._add_action_button(
            self.pomodoro_panel,
            "停止",
            "pause",
        )
        self._add_action_button(self.pomodoro_panel, "再起動", "restart")

        self.bgm_button = self._add_button("BGM  ›", self._toggle_bgm)
        self.bgm_panel = tk.Frame(
            self.container,
            background=self.BACKGROUND,
        )
        self.bgm_muted_var = tk.BooleanVar(master=self.window, value=False)
        self.mute_button = tk.Checkbutton(
            self.bgm_panel,
            text="ミュート",
            variable=self.bgm_muted_var,
            command=lambda: self._run_action("mute"),
            anchor="w",
            background=self.BACKGROUND,
            activebackground=self.HOVER,
            foreground=self.TEXT,
            activeforeground=self.TEXT,
            font=self.FONT,
            borderwidth=0,
            highlightthickness=0,
            padx=22,
            pady=5,
        )
        self.mute_button.pack(fill="x")
        self.action_buttons["mute"] = self.mute_button
        self.volume_label = tk.Label(
            self.bgm_panel,
            text="音量: 50%",
            anchor="w",
            background=self.BACKGROUND,
            foreground=self.DISABLED_TEXT,
            font=self.FONT,
            padx=26,
            pady=5,
        )
        self.volume_label.pack(fill="x")
        self._add_action_button(self.bgm_panel, "音量を上げる", "volume_up")
        self._add_action_button(self.bgm_panel, "音量を下げる", "volume_down")
        self._add_separator(self.bgm_panel, padx=22)
        self._add_action_button(self.bgm_panel, "次の曲", "next_track")

        self._add_separator()
        self.exit_button = self._add_button(
            "終了",
            lambda: self._run_action("quit"),
        )
        self.action_buttons["quit"] = self.exit_button

    def _add_label(self, text: str) -> tk.Label:
        label = tk.Label(
            self.container,
            text=text,
            width=28,
            anchor="w",
            background=self.BACKGROUND,
            foreground=self.DISABLED_TEXT,
            font=self.FONT,
            padx=10,
            pady=6,
        )
        label.pack(fill="x")
        return label

    def _add_button(
        self,
        text: str,
        command: Callable[[], None],
    ) -> tk.Button:
        button = tk.Button(
            self.container,
            text=text,
            command=command,
            width=28,
            anchor="w",
            background=self.BACKGROUND,
            activebackground=self.HOVER,
            foreground=self.TEXT,
            activeforeground=self.TEXT,
            font=self.FONT,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            padx=10,
            pady=5,
        )
        button.pack(fill="x")
        return button

    def _add_action_button(
        self,
        parent: tk.Misc,
        text: str,
        action: str,
    ) -> tk.Button:
        button = tk.Button(
            parent,
            text=text,
            command=lambda: self._run_action(action),
            anchor="w",
            background=self.BACKGROUND,
            activebackground=self.HOVER,
            foreground=self.TEXT,
            activeforeground=self.TEXT,
            font=self.FONT,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            padx=26,
            pady=5,
        )
        button.pack(fill="x")
        self.action_buttons[action] = button
        return button

    def _add_separator(
        self,
        parent: tk.Misc | None = None,
        *,
        padx: int = 6,
    ) -> None:
        separator = tk.Frame(
            parent or self.container,
            background="#d0d0d0",
            height=1,
        )
        separator.pack(fill="x", padx=padx, pady=2)

    def refresh(
        self,
        *,
        status_text: str,
        paused: bool,
        bgm_muted: bool,
        bgm_volume: int,
    ) -> None:
        self.status_label.configure(text=status_text)
        self.pause_button.configure(text="再開" if paused else "停止")
        self.bgm_muted_var.set(bgm_muted)
        self.volume_label.configure(text=f"音量: {bgm_volume}%")

    def toggle(self) -> None:
        if self.window.state() == "normal":
            self.hide()
        else:
            self.show()

    def show(self) -> None:
        self._hide_panels()
        self._anchor_x = self.window.winfo_pointerx()
        self._anchor_y = self.window.winfo_pointery()
        self.window.update_idletasks()
        self._move_near_anchor()
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()

    def hide(self) -> None:
        self.window.withdraw()
        self._hide_panels()

    def _toggle_pomodoro(self) -> None:
        self._toggle_panel(self.pomodoro_panel, self.pomodoro_button)

    def _toggle_bgm(self) -> None:
        self._toggle_panel(self.bgm_panel, self.bgm_button)

    def _toggle_panel(self, panel: tk.Frame, after: tk.Widget) -> None:
        was_visible = bool(panel.winfo_manager())
        self._hide_panels()
        if not was_visible:
            panel.pack(fill="x", after=after)
        self.window.update_idletasks()
        self._move_near_anchor()

    def _hide_panels(self) -> None:
        self.pomodoro_panel.pack_forget()
        self.bgm_panel.pack_forget()

    def _move_near_anchor(self) -> None:
        width = max(self.WIDTH, self.window.winfo_reqwidth())
        height = self.window.winfo_reqheight()
        screen_width = self.window.winfo_screenwidth()
        screen_height = self.window.winfo_screenheight()
        x = max(0, min(self._anchor_x - width, screen_width - width))
        y = max(0, min(self._anchor_y - height, screen_height - height))
        self.window.geometry(f"{width}x{height}+{x}+{y}")

    def _on_focus_out(self, _event: tk.Event) -> None:
        self.window.after_idle(self._hide_if_focus_left)

    def _hide_if_focus_left(self) -> None:
        focused = self.window.focus_get()
        if focused is None or focused.winfo_toplevel() is not self.window:
            self.hide()

    def _run_action(self, action: str) -> None:
        self.hide()
        self._on_action(action)
