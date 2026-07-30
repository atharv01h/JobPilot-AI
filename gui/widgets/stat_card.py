"""
Stat card widget for the Dashboard page.
Displays a metric with title, value, icon, and subtle animation.
"""

from __future__ import annotations

import customtkinter as ctk

from config.constants import COLORS, FONTS


class StatCard(ctk.CTkFrame):
    """
    A premium stat card showing:
    - Icon (emoji)
    - Title label
    - Large numeric value
    - Subtitle/description
    """

    def __init__(
        self,
        master,
        title: str,
        value: str | int,
        icon: str,
        subtitle: str = "",
        accent_color: str = COLORS["accent_primary"],
        **kwargs,
    ):
        super().__init__(
            master,
            fg_color=COLORS["bg_card"],
            corner_radius=16,
            border_width=1,
            border_color=COLORS["border"],
            **kwargs,
        )

        self._accent = accent_color
        self._value_var = ctk.StringVar(value=str(value))

        self._build(title, icon, subtitle)

        # Hover effect
        self.bind("<Enter>", self._on_hover)
        self.bind("<Leave>", self._on_leave)

    def _build(self, title: str, icon: str, subtitle: str) -> None:
        self.grid_columnconfigure(0, weight=1)

        # Coloured accent bar at top
        accent_bar = ctk.CTkFrame(
            self, height=4, fg_color=self._accent, corner_radius=2
        )
        accent_bar.grid(row=0, column=0, sticky="ew", padx=0, pady=(0, 0))

        # Content frame
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.grid(row=1, column=0, padx=20, pady=16, sticky="nsew")
        content.grid_columnconfigure(1, weight=1)

        # Icon
        icon_lbl = ctk.CTkLabel(
            content,
            text=icon,
            font=("Segoe UI Emoji", 28),
            text_color=self._accent,
        )
        icon_lbl.grid(row=0, column=0, rowspan=2, padx=(0, 16), sticky="w")

        # Title
        title_lbl = ctk.CTkLabel(
            content,
            text=title,
            font=FONTS["body_sm"],
            text_color=COLORS["text_secondary"],
            anchor="w",
        )
        title_lbl.grid(row=0, column=1, sticky="w")

        # Value
        self._value_lbl = ctk.CTkLabel(
            content,
            textvariable=self._value_var,
            font=FONTS["heading_lg"],
            text_color=COLORS["text_primary"],
            anchor="w",
        )
        self._value_lbl.grid(row=1, column=1, sticky="w")

        # Subtitle
        if subtitle:
            sub_lbl = ctk.CTkLabel(
                self,
                text=subtitle,
                font=FONTS["body_sm"],
                text_color=COLORS["text_muted"],
                anchor="w",
            )
            sub_lbl.grid(row=2, column=0, padx=20, pady=(0, 12), sticky="w")

    def set_value(self, value: str | int) -> None:
        self._value_var.set(str(value))

    def _on_hover(self, _event=None) -> None:
        self.configure(border_color=self._accent)

    def _on_leave(self, _event=None) -> None:
        self.configure(border_color=COLORS["border"])
