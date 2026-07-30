"""
Analytics Page — shows job status distributions and application performance statistics.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import customtkinter as ctk

from config.constants import COLORS, FONTS

if TYPE_CHECKING:
    from gui.app import App


class AnalyticsPage(ctk.CTkFrame):
    def __init__(self, master, app: App, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_primary"], **kwargs)
        self._app = app
        self._stats_cards: dict[str, ctk.CTkProgressBar] = {}
        self._stats_lbls: dict[str, ctk.CTkLabel] = {}
        self._build()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=32, pady=(24, 0), sticky="ew")

        ctk.CTkLabel(
            header,
            text="Platform Analytics",
            font=FONTS["heading_xl"],
            text_color=COLORS["text_primary"],
        ).pack(side="left")

        # Scrollable layout
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.grid(row=1, column=0, padx=32, pady=16, sticky="nsew")
        self.grid_rowconfigure(1, weight=1)
        scroll.grid_columnconfigure(0, weight=1)

        # Status Breakdown Card
        card = ctk.CTkFrame(
            scroll,
            fg_color=COLORS["bg_card"],
            corner_radius=16,
            border_width=1,
            border_color=COLORS["border"],
        )
        card.pack(fill="x", pady=8)
        card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            card,
            text="Job Status Distribution Breakdown",
            font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"],
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, padx=20, pady=(16, 12), sticky="w")

        statuses = [
            ("SUBMITTED", "Submitted / Completed Applications", COLORS["accent_green"]),
            ("APPLIED", "Applied via Platform", COLORS["accent_green"]),
            ("FAILED", "Failed Automation Attempts", COLORS["accent_red"]),
            ("SKIPPED", "Skipped / Ineligible Jobs", COLORS["accent_cyan"]),
            ("REDIRECTED", "Redirected to Company Sites", COLORS["accent_orange"]),
            (
                "EXTERNAL_REQUIRED",
                "External Application Needed",
                COLORS["accent_orange"],
            ),
            ("ERROR", "Error / Blocked (CAPTCHA/OTP)", COLORS["accent_red"]),
            ("NEW", "New Scraped / Unprocessed Jobs", COLORS["accent_primary"]),
        ]

        for i, (key, label, color) in enumerate(statuses):
            # Row label
            lbl = ctk.CTkLabel(
                card,
                text=label,
                font=FONTS["body_sm"],
                text_color=COLORS["text_secondary"],
                anchor="w",
            )
            lbl.grid(row=i + 1, column=0, padx=20, pady=8, sticky="w")

            # Progress row frame
            bar_frame = ctk.CTkFrame(card, fg_color="transparent")
            bar_frame.grid(row=i + 1, column=1, padx=20, pady=8, sticky="ew")
            bar_frame.grid_columnconfigure(0, weight=1)

            pbar = ctk.CTkProgressBar(bar_frame, progress_color=color, height=8)
            pbar.grid(row=0, column=0, sticky="ew")
            pbar.set(0.0)
            self._stats_cards[key] = pbar

            val_lbl = ctk.CTkLabel(
                bar_frame,
                text="0 (0.0%)",
                font=FONTS["mono"],
                text_color=COLORS["text_primary"],
                anchor="e",
                width=100,
            )
            val_lbl.grid(row=0, column=1, padx=(10, 0))
            self._stats_lbls[key] = val_lbl

        self.refresh()

    def refresh(self) -> None:
        async def _load():
            from core.database import get_database

            db = get_database()
            stats = await db.get_analytics_stats()
            total = sum(stats.values())
            self.after(0, lambda: self._update_view(stats, total))

        self._app.run_async(_load())

    def _update_view(self, stats: dict, total: int) -> None:
        for key, pbar in self._stats_cards.items():
            count = stats.get(key, 0)
            pct = (count / total) if total > 0 else 0.0

            pbar.set(pct)
            self._stats_lbls[key].configure(text=f"{count} ({pct * 100:.1f}%)")

    def on_show(self) -> None:
        self.refresh()
