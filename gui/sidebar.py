"""
Navigation sidebar component.
Vertical nav bar with icon+label buttons and active state highlighting.
"""

from __future__ import annotations

from collections.abc import Callable

import customtkinter as ctk

from config.constants import COLORS, FONTS, SIDEBAR_WIDTH

NAV_ITEMS: list[tuple[str, str, str]] = [
    ("dashboard", "📊", "Dashboard"),
    ("jobs", "💼", "Jobs"),
    ("linkedin_easy_apply", "⚡", "LinkedIn Easy Apply"),
    ("queue", "⏳", "Queue"),
    ("applications", "✅", "Applications"),
    ("browser", "🌐", "Browser"),
    ("ai", "🧠", "AI Page"),
    ("resume", "📄", "Resume"),
    ("profile", "👤", "Profile"),
    ("scheduler", "📅", "Scheduler"),
    ("analytics", "📈", "Analytics"),
    ("settings", "⚙️", "Settings"),
    ("logs", "📋", "Logs"),
    ("diagnostics", "🛠️", "Diagnostics"),
    ("dependencies", "📦", "Dependencies"),
]


class Sidebar(ctk.CTkFrame):
    """
    Vertical navigation sidebar.
    Calls on_navigate(page_key) when a nav item is clicked.
    """

    def __init__(
        self,
        master,
        on_navigate: Callable[[str], None],
        **kwargs,
    ):
        super().__init__(
            master,
            width=SIDEBAR_WIDTH,
            fg_color=COLORS["bg_sidebar"],
            corner_radius=0,
            **kwargs,
        )
        self.grid_propagate(False)
        self._on_navigate = on_navigate
        self._active_key: str | None = None
        self._buttons: dict[str, ctk.CTkButton] = {}
        self._build()

    def _build(self) -> None:
        self.grid_rowconfigure(99, weight=1)  # Push items up

        # ── Logo / Branding ──────────────────────────────────────────────────
        logo_frame = ctk.CTkFrame(self, fg_color="transparent")
        logo_frame.grid(row=0, column=0, padx=16, pady=(24, 8), sticky="ew")

        ctk.CTkLabel(
            logo_frame,
            text="🤖",
            font=("Segoe UI Emoji", 30),
        ).pack(side="left")

        name_frame = ctk.CTkFrame(logo_frame, fg_color="transparent")
        name_frame.pack(side="left", padx=(8, 0))

        ctk.CTkLabel(
            name_frame,
            text="JobPilot AI",
            font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"],
            anchor="w",
        ).pack(anchor="w")

        ctk.CTkLabel(
            name_frame,
            text="Job Assistant",
            font=FONTS["body_sm"],
            text_color=COLORS["text_muted"],
            anchor="w",
        ).pack(anchor="w")

        # Divider
        ctk.CTkFrame(self, height=1, fg_color=COLORS["border"]).grid(
            row=1, column=0, padx=12, pady=(8, 16), sticky="ew"
        )

        # ── Nav Items ────────────────────────────────────────────────────────
        for i, (key, icon, label) in enumerate(NAV_ITEMS):
            btn = ctk.CTkButton(
                self,
                text=f"  {icon}   {label}",
                font=FONTS["body_md"],
                anchor="w",
                height=42,
                corner_radius=10,
                fg_color="transparent",
                hover_color=COLORS["bg_hover"],
                text_color=COLORS["text_secondary"],
                command=lambda k=key: self._nav_click(k),
            )
            btn.grid(row=i + 2, column=0, padx=10, pady=3, sticky="ew")
            self._buttons[key] = btn

        # ── Footer ───────────────────────────────────────────────────────────
        ctk.CTkLabel(
            self,
            text="v1.0.0  •  NVIDIA NIM",
            font=FONTS["body_sm"],
            text_color=COLORS["text_muted"],
        ).grid(row=100, column=0, padx=16, pady=12)

    def _nav_click(self, key: str) -> None:
        self.set_active(key)
        self._on_navigate(key)

    def set_active(self, key: str) -> None:
        # Deactivate previous
        if self._active_key and self._active_key in self._buttons:
            self._buttons[self._active_key].configure(
                fg_color="transparent",
                text_color=COLORS["text_secondary"],
                font=FONTS["body_md"],
            )

        self._active_key = key

        if key in self._buttons:
            self._buttons[key].configure(
                fg_color=COLORS["accent_primary"],
                text_color="#FFFFFF",
                font=FONTS["heading_sm"],
            )
