"""
Scheduler Page — configure automatic scraping schedules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import customtkinter as ctk

from config.constants import COLORS, FONTS

if TYPE_CHECKING:
    from gui.app import App


class SchedulerPage(ctk.CTkFrame):
    def __init__(self, master, app: App, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_primary"], **kwargs)
        self._app = app
        self._build()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=32, pady=(24, 0), sticky="ew")

        ctk.CTkLabel(
            header,
            text="Scraping & Application Scheduler",
            font=FONTS["heading_xl"],
            text_color=COLORS["text_primary"],
        ).pack(side="left")

        # Configurations Frame
        card = ctk.CTkFrame(
            self,
            fg_color=COLORS["bg_card"],
            corner_radius=16,
            border_width=1,
            border_color=COLORS["border"],
        )
        card.grid(row=1, column=0, padx=32, pady=16, sticky="new")
        card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            card,
            text="Scheduler Status & Intervals",
            font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"],
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, padx=20, pady=(16, 8), sticky="w")

        # Status
        self._lbl_status = self._create_row(card, 1, "Scheduler Status:")

        # Interval field
        ctk.CTkLabel(
            card,
            text="Scrape Interval (Minutes):",
            font=FONTS["body_sm"],
            text_color=COLORS["text_secondary"],
            anchor="w",
        ).grid(row=2, column=0, padx=20, pady=8, sticky="w")

        self._interval_var = ctk.StringVar(value="360")
        self._interval_entry = ctk.CTkEntry(
            card,
            textvariable=self._interval_var,
            font=FONTS["body_sm"],
            height=32,
            width=120,
            corner_radius=6,
        )
        self._interval_entry.grid(row=2, column=1, padx=20, pady=8, sticky="w")

        # Controls row
        btn_frame = ctk.CTkFrame(card, fg_color="transparent")
        btn_frame.grid(
            row=3, column=0, columnspan=2, padx=20, pady=(16, 20), sticky="w"
        )

        self._btn_toggle = ctk.CTkButton(
            btn_frame,
            text="Start Scheduler",
            font=FONTS["body_sm"],
            height=34,
            width=150,
            fg_color=COLORS["accent_primary"],
            hover_color=COLORS["accent_secondary"],
            command=self._toggle_scheduler,
        )
        self._btn_toggle.pack(side="left", padx=4)

        ctk.CTkButton(
            btn_frame,
            text="⚡ Run Search Now",
            font=FONTS["body_sm"],
            height=34,
            width=150,
            fg_color=COLORS["accent_green"],
            hover_color="#16A34A",
            command=self._run_now,
        ).pack(side="left", padx=4)

        self.refresh()

    def _create_row(self, parent: ctk.CTkFrame, row: int, label: str) -> ctk.CTkLabel:
        lbl = ctk.CTkLabel(
            parent,
            text=label,
            font=FONTS["body_sm"],
            text_color=COLORS["text_secondary"],
            anchor="w",
        )
        lbl.grid(row=row, column=0, padx=20, pady=8, sticky="w")

        val_lbl = ctk.CTkLabel(
            parent,
            text="--",
            font=FONTS["body_sm"],
            text_color=COLORS["text_primary"],
            anchor="w",
        )
        val_lbl.grid(row=row, column=1, padx=20, pady=8, sticky="w")
        return val_lbl

    def _toggle_scheduler(self) -> None:
        from services.scheduler_service import get_scheduler

        s = get_scheduler()

        if s.is_running:
            s.stop()
        else:
            try:
                mins = int(self._interval_var.get())
                s.apply_interval(mins)
            except ValueError:
                pass
            s.start()
        self.refresh()

    def _run_now(self) -> None:
        # Switch to Jobs and run search
        self._app._navigate("jobs")
        page = self._app._pages.get("jobs")
        if page and hasattr(page, "start_search_flow"):
            page.start_search_flow()

    def refresh(self) -> None:
        from services.scheduler_service import get_scheduler

        s = get_scheduler()

        if s.is_running:
            self._lbl_status.configure(text="ACTIVE", text_color=COLORS["accent_green"])
            self._btn_toggle.configure(
                text="Stop Scheduler", fg_color=COLORS["bg_hover"]
            )
        else:
            self._lbl_status.configure(text="INACTIVE", text_color=COLORS["accent_red"])
            self._btn_toggle.configure(
                text="Start Scheduler", fg_color=COLORS["accent_primary"]
            )

    def on_show(self) -> None:
        self.refresh()
