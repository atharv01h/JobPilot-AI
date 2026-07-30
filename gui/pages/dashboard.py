"""
Dashboard page — overview stats, system telemetry, and rolling latencies.
Uses StateManager as the single source of truth for all live telemetry.
Calculates all stats directly from the real database schema.
"""

from __future__ import annotations

from core.logger import get_logger

logger = get_logger(__name__)

import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import customtkinter as ctk
from PIL import Image

from config.constants import COLORS, FONTS
from gui.widgets.stat_card import StatCard
from services.state_manager import get_state_manager

if TYPE_CHECKING:
    from gui.app import App


class DashboardPage(ctk.CTkFrame):
    def __init__(self, master, app: App, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_primary"], **kwargs)
        self._app = app
        self._cards: dict = {}
        self._after_ids: set[str] = set()

        self._build()

        # Register StateManager listener
        get_state_manager().register_listener(self._on_state_changed)

        # Initial refresh
        self.refresh()

    def safe_after(self, delay_ms: int, callback) -> str:
        """Schedule a timer and track its ID for safe cleanup."""
        if not self.winfo_exists():
            return ""
        aid = super().after(delay_ms, callback)
        self._after_ids.add(aid)
        return aid

    def destroy(self) -> None:
        """Cancel all pending timers to prevent invalid command name errors."""
        try:
            get_state_manager().unregister_listener(self._on_state_changed)
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)

        for aid in list(self._after_ids):
            try:
                self.after_cancel(aid)
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)
        self._after_ids.clear()
        super().destroy()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        # ── Header (Row 0) ────────────────────────────────────────────────────
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=32, pady=(24, 0), sticky="ew")

        ctk.CTkLabel(
            header,
            text="Dashboard",
            font=FONTS["heading_xl"],
            text_color=COLORS["text_primary"],
        ).pack(side="left")

        self._time_lbl = ctk.CTkLabel(
            header,
            text="",
            font=FONTS["body_sm"],
            text_color=COLORS["text_muted"],
        )
        self._time_lbl.pack(side="right")
        self._update_time()

        ctk.CTkLabel(
            self,
            text="Autonomous AI Job Application Platform",
            font=FONTS["body_md"],
            text_color=COLORS["text_muted"],
            anchor="w",
        ).grid(row=1, column=0, padx=32, pady=(4, 12), sticky="w")

        # ── Stat Cards Grid (Row 2) ───────────────────────────────────────────
        cards_frame = ctk.CTkFrame(self, fg_color="transparent")
        cards_frame.grid(row=2, column=0, padx=32, pady=(0, 12), sticky="new")
        cards_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        card_data = [
            (
                "apps_today",
                "Applications Today",
                "0",
                "📅",
                "Today's runs",
                COLORS["accent_green"],
            ),
            (
                "jobs_found",
                "Jobs Found (Total)",
                "0",
                "🔍",
                "Scraped count",
                COLORS["accent_cyan"],
            ),
            (
                "success_rate",
                "Success Rate",
                "0.0%",
                "📈",
                "Completed ratio",
                COLORS["accent_orange"],
            ),
            (
                "queue_size",
                "Queue Pending",
                "0",
                "📥",
                "In queue",
                COLORS["accent_primary"],
            ),
        ]
        for col, (key, title, val, icon, sub, color) in enumerate(card_data):
            card = StatCard(
                cards_frame,
                title=title,
                value=val,
                icon=icon,
                subtitle=sub,
                accent_color=color,
            )
            card.grid(row=0, column=col, padx=8, pady=8, sticky="nsew")
            self._cards[key] = card

        # ── Main Split Frame & Telemetry (Row 3) ──────────────────────────────
        # Use scrollable frame for main content so screenshot doesn't clip
        self._main_scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._main_scroll.grid(row=3, column=0, padx=32, pady=(0, 20), sticky="nsew")
        self._main_scroll.grid_columnconfigure(0, weight=1)

        split_frame = ctk.CTkFrame(self._main_scroll, fg_color="transparent")
        split_frame.pack(fill="x", pady=(0, 12))
        split_frame.grid_columnconfigure(0, weight=1)
        split_frame.grid_columnconfigure(1, weight=1)

        # Left Column: Telemetry & Latencies
        telemetry_frame = ctk.CTkFrame(
            split_frame,
            fg_color=COLORS["bg_card"],
            corner_radius=16,
            border_width=1,
            border_color=COLORS["border"],
        )
        telemetry_frame.grid(row=0, column=0, padx=(0, 8), pady=0, sticky="nsew")
        telemetry_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            telemetry_frame,
            text="💻  System Telemetry & Latencies",
            font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"],
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, padx=20, pady=(16, 8), sticky="w")

        self._lbl_cpu = self._create_telemetry_row(telemetry_frame, 1, "CPU Usage:")
        self._lbl_ram = self._create_telemetry_row(telemetry_frame, 2, "RAM Usage:")
        self._lbl_gpu = self._create_telemetry_row(telemetry_frame, 3, "GPU Active:")
        self._lbl_browser_mem = self._create_telemetry_row(
            telemetry_frame, 4, "Browser Memory:"
        )
        self._lbl_avg_apply = self._create_telemetry_row(
            telemetry_frame, 5, "Average Apply Time:"
        )
        self._lbl_llm_lat = self._create_telemetry_row(
            telemetry_frame, 6, "LLM Latency:"
        )
        self._lbl_vis_lat = self._create_telemetry_row(
            telemetry_frame, 7, "Vision Latency:"
        )

        # Right Column: Orchestration & Session Status
        orch_frame = ctk.CTkFrame(
            split_frame,
            fg_color=COLORS["bg_card"],
            corner_radius=16,
            border_width=1,
            border_color=COLORS["border"],
        )
        orch_frame.grid(row=0, column=1, padx=(8, 0), pady=0, sticky="nsew")
        orch_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            orch_frame,
            text="🤖  AI Orchestrator & Session Status",
            font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"],
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, padx=20, pady=(16, 8), sticky="w")

        self._lbl_model = self._create_telemetry_row(orch_frame, 1, "Running AI Model:")
        self._lbl_task = self._create_telemetry_row(orch_frame, 2, "Running Task:")
        self._lbl_website = self._create_telemetry_row(
            orch_frame, 3, "Current Website:"
        )
        self._lbl_browser = self._create_telemetry_row(
            orch_frame, 4, "Current Browser:"
        )
        self._lbl_ats = self._create_telemetry_row(orch_frame, 5, "Current ATS:")
        self._lbl_failures = self._create_telemetry_row(orch_frame, 6, "Failures:")

        # ── Bottom Column: Live Viewport Screenshot Preview ──────────────────
        self._screenshot_card = ctk.CTkFrame(
            self._main_scroll,
            fg_color=COLORS["bg_card"],
            corner_radius=16,
            border_width=1,
            border_color=COLORS["border"],
        )
        self._screenshot_card.pack(fill="x", pady=8)
        self._screenshot_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self._screenshot_card,
            text="📸 Live Viewport Preview",
            font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"],
            anchor="w",
        ).pack(padx=20, pady=(16, 8), anchor="w")

        self._lbl_screenshot = ctk.CTkLabel(
            self._screenshot_card,
            text="No screenshot available",
            font=FONTS["body_sm"],
            text_color=COLORS["text_muted"],
        )
        self._lbl_screenshot.pack(padx=20, pady=(8, 20))

    def _create_telemetry_row(
        self, parent: ctk.CTkFrame, row: int, label: str
    ) -> ctk.CTkLabel:
        lbl = ctk.CTkLabel(
            parent,
            text=label,
            font=FONTS["body_sm"],
            text_color=COLORS["text_secondary"],
            anchor="w",
        )
        lbl.grid(row=row, column=0, padx=20, pady=6, sticky="w")

        val_lbl = ctk.CTkLabel(
            parent,
            text="--",
            font=FONTS["body_sm"],
            text_color=COLORS["text_primary"],
            anchor="e",
        )
        val_lbl.grid(row=row, column=1, padx=20, pady=6, sticky="e")
        return val_lbl

    def _update_time(self) -> None:
        if not self.winfo_exists():
            return
        now = datetime.now(timezone.utc).strftime("%A, %d %B %Y  •  %H:%M")
        self._time_lbl.configure(text=now)
        self.safe_after(30000, self._update_time)

    def _on_state_changed(self) -> None:
        """Callback triggered when StateManager variables are modified."""
        if not self.winfo_exists():
            return
        
        # Debounce to prevent UI freeze when state updates rapidly
        if getattr(self, "_refresh_pending", False):
            return
        self._refresh_pending = True
        self.after(500, self._do_refresh_debounced)

    def _do_refresh_debounced(self) -> None:
        if not self.winfo_exists():
            return
        self._refresh_pending = False
        self.refresh()

    def refresh(self) -> None:
        """Reload database statistics and populate StateManager updates."""

        async def _load():
            from config.settings import get_settings
            from core.database import get_database
            from services.queue_manager import get_application_queue

            db = get_database()
            settings = get_settings()
            q = get_application_queue()

            # Query stats from database
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            stats = await db.get_dashboard_stats(today_str)

            apps_today = stats["apps_today"]
            jobs_found = stats["jobs_found"]
            failures = stats["failures"]
            successes = stats["successes"]

            llm_lat = f"{stats['llm_lat']} ms" if stats["llm_lat"] else "Unavailable"
            vis_lat = f"{stats['vis_lat']} ms" if stats["vis_lat"] else "Unavailable"
            avg_apply = (
                f"{stats['avg_total'] / 1000.0:.2f} s"
                if stats["avg_total"]
                else "Unavailable"
            )

            # Compute Success Rate
            total_attempts = successes + failures
            success_rate = (
                f"{(successes / total_attempts) * 100:.1f}%"
                if total_attempts > 0
                else "100.0%"
            )

            # Queue pending size
            q_size = await q.size()

            self.after(
                0,
                lambda: self._update_gui_stats(
                    apps_today,
                    jobs_found,
                    success_rate,
                    q_size,
                    llm_lat,
                    vis_lat,
                    avg_apply,
                    settings.llm_model,
                    failures,
                ),
            )

        self._app.run_async(_load())

    def _update_gui_stats(
        self,
        today_runs,
        total_jobs,
        success_rate,
        q_size,
        llm_lat,
        vis_lat,
        avg_apply,
        model,
        failures,
    ):
        if not self.winfo_exists():
            return

        # 1. Update card totals
        self._cards["apps_today"].set_value(today_runs)
        self._cards["jobs_found"].set_value(total_jobs)
        self._cards["success_rate"].set_value(success_rate)
        self._cards["queue_size"].set_value(q_size)

        # 2. Update DB latencies & model
        self._lbl_avg_apply.configure(text=avg_apply)
        self._lbl_llm_lat.configure(text=llm_lat)
        self._lbl_vis_lat.configure(text=vis_lat)
        self._lbl_model.configure(text=model.split("/")[-1] if model else "Unavailable")
        self._lbl_failures.configure(text=f"{failures} failed attempts")

        # 3. Pull live telemetry from StateManager snapshot
        stm = get_state_manager()
        snap = stm.get_snapshot()

        # Parse live progress text: "{brave_pid}|{brave_mem}|{cpu}|{mem}|{gpu}"
        telemetry_raw = snap.live_progress_text
        cpu_val = "Unavailable"
        ram_val = "Unavailable"
        gpu_val = "Unavailable"
        browser_mem_val = "Unavailable"

        if telemetry_raw and "|" in telemetry_raw:
            parts = telemetry_raw.split("|")
            if len(parts) >= 5:
                browser_mem_val = (
                    parts[1] if parts[1] != "Unavailable" else "Unavailable"
                )
                cpu_val = parts[2]
                ram_val = parts[3]
                gpu_val = parts[4]

        self._lbl_cpu.configure(text=cpu_val)
        self._lbl_ram.configure(text=ram_val)
        self._lbl_gpu.configure(text=gpu_val)
        self._lbl_browser_mem.configure(text=browser_mem_val)

        # Pull active website, ATS, browser and running task (app_state)
        self._lbl_browser.configure(text=snap.browser_status)
        self._lbl_ats.configure(text=snap.current_ats)
        self._lbl_website.configure(text=snap.current_website)
        self._lbl_task.configure(text=snap.app_state.value)

        # 4. Update Screenshot Preview
        screenshot_path = "logs/watchdog_diagnostic.png"
        last_screenshot = "logs/last_screenshot.png"
        active_path = (
            screenshot_path
            if os.path.exists(screenshot_path)
            else (last_screenshot if os.path.exists(last_screenshot) else None)
        )

        if active_path:
            try:
                img = Image.open(active_path)
                w, h = img.size
                ratio = 760 / w
                target_h = int(h * ratio)
                ctk_img = ctk.CTkImage(
                    light_image=img, dark_image=img, size=(760, target_h)
                )
                self._lbl_screenshot.configure(image=ctk_img, text="")
            except Exception as e:
                self._lbl_screenshot.configure(
                    text=f"Failed to load screenshot: {e}", image=None
                )
        else:
            self._lbl_screenshot.configure(
                image=None,
                text="Screenshot will appear here during active browser runs.",
            )

    def on_show(self) -> None:
        self.refresh()
