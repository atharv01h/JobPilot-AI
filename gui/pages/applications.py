"""
Applications Page — shows history of job application attempts and a live run monitor tab.
"""

from __future__ import annotations

from core.logger import get_logger

logger = get_logger(__name__)

import os
from typing import TYPE_CHECKING

import customtkinter as ctk
from PIL import Image

from config.constants import COLORS, FONTS

if TYPE_CHECKING:
    from gui.app import App


class ApplicationsPage(ctk.CTkFrame):
    def __init__(self, master, app: App, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_primary"], **kwargs)
        self._app = app
        self._attempts: list[dict] = []
        self._after_ids: set[str] = set()
        self._debounce_id: str | None = None
        self._build()

        # Subscribe to StateManager
        from services.state_manager import get_state_manager

        get_state_manager().register_listener(self._on_state_changed)

        # Start periodic polling for live screenshot and state updates
        self._poll_live_state()

    def after(self, delay_ms: int, callback=None, *args) -> str:
        """Schedule a timer and track its ID for safe cleanup."""
        if not self.winfo_exists():
            return ""
        aid = super().after(delay_ms, callback, *args)
        self._after_ids.add(aid)
        return aid

    def destroy(self) -> None:
        """Cancel all timers and unsubscribe."""
        if self._debounce_id:
            try:
                self.after_cancel(self._debounce_id)
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)
        try:
            from services.state_manager import get_state_manager

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

    def _on_state_changed(self) -> None:
        if self.winfo_exists():
            # Refresh history if in history tab, otherwise update live monitor
            active_tab = self._tabview.get()
            if active_tab == "Attempts History":
                self.refresh()
            else:
                self._update_live_monitor()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=32, pady=(24, 0), sticky="ew")

        ctk.CTkLabel(
            header,
            text="Application Center",
            font=FONTS["heading_xl"],
            text_color=COLORS["text_primary"],
        ).pack(side="left")

        # Tabview Layout
        self._tabview = ctk.CTkTabview(self, fg_color="transparent")
        self._tabview.grid(row=1, column=0, padx=32, pady=(0, 20), sticky="nsew")

        self._tab_history = self._tabview.add("Attempts History")
        self._tab_live = self._tabview.add("Live Run Monitor")

        # Configure tabs
        self._tab_history.grid_columnconfigure(0, weight=1)
        self._tab_history.grid_rowconfigure(1, weight=1)

        self._tab_live.grid_columnconfigure(0, weight=1)
        self._tab_live.grid_columnconfigure(1, weight=1)
        self._tab_live.grid_rowconfigure(0, weight=1)

        self._build_history_tab()
        self._build_live_tab()

    def _build_history_tab(self) -> None:
        # Filters Bar inside history tab
        filter_bar = ctk.CTkFrame(
            self._tab_history,
            fg_color=COLORS["bg_card"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
        )
        filter_bar.grid(row=0, column=0, pady=(0, 12), sticky="ew")

        ctk.CTkLabel(filter_bar, text="🔍", font=FONTS["body_md"]).pack(
            side="left", padx=(12, 6)
        )

        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._on_search_keypress())
        self._search_entry = ctk.CTkEntry(
            filter_bar,
            placeholder_text="Filter by Company or Role...",
            textvariable=self._search_var,
            width=300,
            height=34,
            corner_radius=6,
        )
        self._search_entry.pack(side="left", padx=6, pady=8)

        # Actions frame on right side of filter bar
        btn_frame = ctk.CTkFrame(filter_bar, fg_color="transparent")
        btn_frame.pack(side="right", padx=12)

        ctk.CTkButton(
            btn_frame,
            text="📤  Export CSV",
            fg_color=COLORS["bg_hover"],
            hover_color=COLORS["accent_primary"],
            text_color=COLORS["text_primary"],
            height=32,
            width=120,
            corner_radius=6,
            command=self._export_csv,
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            btn_frame,
            text="📋  Open Log",
            fg_color=COLORS["bg_hover"],
            hover_color=COLORS["accent_primary"],
            text_color=COLORS["text_primary"],
            height=32,
            width=110,
            corner_radius=6,
            command=self._open_log,
        ).pack(side="left", padx=4)

        # Scrollable Attempts Table
        self._scroll = ctk.CTkScrollableFrame(
            self._tab_history,
            fg_color=COLORS["bg_secondary"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
        )
        self._scroll.grid(row=1, column=0, sticky="nsew")
        self._scroll.grid_columnconfigure(0, weight=1)

    def _build_live_tab(self) -> None:
        # Left Side: Status and Telemetry panel
        self._live_telemetry_card = ctk.CTkFrame(
            self._tab_live,
            fg_color=COLORS["bg_card"],
            corner_radius=16,
            border_width=1,
            border_color=COLORS["border"],
        )
        self._live_telemetry_card.grid(
            row=0, column=0, padx=(0, 10), pady=10, sticky="nsew"
        )
        self._live_telemetry_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            self._live_telemetry_card,
            text="🤖 Live Automator Status",
            font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"],
        ).grid(row=0, column=0, columnspan=2, padx=20, pady=(16, 12), sticky="w")

        self._lbl_live_status = self._create_live_row(
            self._live_telemetry_card, 1, "Orchestrator State:"
        )
        self._lbl_live_website = self._create_live_row(
            self._live_telemetry_card, 2, "Current Website:"
        )
        self._lbl_live_ats = self._create_live_row(
            self._live_telemetry_card, 3, "Current ATS:"
        )
        self._lbl_live_job = self._create_live_row(
            self._live_telemetry_card, 4, "Active Job:"
        )
        self._lbl_live_url = self._create_live_row(
            self._live_telemetry_card, 5, "Active Page URL:"
        )
        self._lbl_live_action = self._create_live_row(
            self._live_telemetry_card, 6, "Current Action:"
        )
        self._lbl_live_selector = self._create_live_row(
            self._live_telemetry_card, 7, "Last Selector:"
        )
        self._lbl_live_milestone = self._create_live_row(
            self._live_telemetry_card, 8, "Current Milestone:"
        )
        self._lbl_live_resume = self._create_live_row(
            self._live_telemetry_card, 9, "Resume Upload:"
        )

        # Timeline indicator
        self._timeline_box = ctk.CTkTextbox(
            self._live_telemetry_card,
            height=120,
            font=FONTS["mono"],
            fg_color=COLORS["bg_secondary"],
            text_color=COLORS["text_primary"],
            wrap="word",
            border_width=1,
            border_color=COLORS["border"],
        )
        self._timeline_box.grid(
            row=10, column=0, columnspan=2, padx=20, pady=16, sticky="ew"
        )
        self._timeline_box.insert(
            "1.0", "--- Progress Timeline ---\n[IDLE] Waiting for job queue to start..."
        )
        self._timeline_box.configure(state="disabled")

        # Right Side: Screenshot Panel
        self._live_screenshot_card = ctk.CTkFrame(
            self._tab_live,
            fg_color=COLORS["bg_card"],
            corner_radius=16,
            border_width=1,
            border_color=COLORS["border"],
        )
        self._live_screenshot_card.grid(
            row=0, column=1, padx=(10, 0), pady=10, sticky="nsew"
        )
        self._live_screenshot_card.grid_columnconfigure(0, weight=1)
        self._live_screenshot_card.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            self._live_screenshot_card,
            text="📸 Live Viewport View",
            font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"],
        ).grid(row=0, column=0, padx=20, pady=(16, 8), sticky="w")

        self._lbl_live_screenshot = ctk.CTkLabel(
            self._live_screenshot_card,
            text="No screenshot available.\nScreenshot appears during active browser runs.",
            font=FONTS["body_sm"],
            text_color=COLORS["text_muted"],
        )
        self._lbl_live_screenshot.grid(row=1, column=0, padx=20, pady=20, sticky="nsew")

    def _create_live_row(
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
            wraplength=200,
        )
        val_lbl.grid(row=row, column=1, padx=20, pady=6, sticky="e")
        return val_lbl

    def _on_search_keypress(self) -> None:
        if self._debounce_id:
            try:
                self.after_cancel(self._debounce_id)
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)
        self._debounce_id = self.after(300, self._apply_filters)

    def _render_attempts(self, items: list[dict]) -> None:
        if not self.winfo_exists():
            return

        for child in self._scroll.winfo_children():
            child.destroy()

        if not items:
            ctk.CTkLabel(
                self._scroll,
                text="No application attempts logged yet.",
                font=FONTS["body_md"],
                text_color=COLORS["text_muted"],
            ).pack(pady=80)
            return

        # Header Row
        header_row = ctk.CTkFrame(self._scroll, fg_color="transparent", height=28)
        header_row.pack(fill="x", padx=8, pady=4)

        col_configs = [
            (0, 140, "w", 0),  # Attempt Date
            (1, 120, "w", 0),  # Company
            (2, 220, "w", 1),  # Job Title
            (3, 110, "center", 0),  # Status Badge
            (4, 200, "w", 0),  # Audit Notes
        ]

        for col_idx, width, anchor, weight in col_configs:
            header_row.grid_columnconfigure(col_idx, minsize=width, weight=weight)

        headers = [
            ("Attempt Date", "w"),
            ("Company", "w"),
            ("Job Title", "w"),
            ("Status", "center"),
            ("Audit Notes", "w"),
        ]
        for idx, (text, align) in enumerate(headers):
            lbl = ctk.CTkLabel(
                header_row,
                text=text.upper(),
                font=FONTS["label"],
                text_color=COLORS["text_muted"],
                anchor=align,
            )
            sticky_val = "w" if align == "w" else ""
            lbl.grid(row=0, column=idx, padx=10, pady=4, sticky=sticky_val)

        # Attempts list
        for i, item in enumerate(items):
            row = ctk.CTkFrame(
                self._scroll,
                fg_color=COLORS["bg_card"] if i % 2 == 0 else COLORS["bg_secondary"],
                height=48,
                corner_radius=8,
            )
            row.pack(fill="x", padx=8, pady=2)

            for col_idx, width, anchor, weight in col_configs:
                row.grid_columnconfigure(col_idx, minsize=width, weight=weight)

            # Date
            date_text = item["attempt_date"][:16].replace("T", " ")
            ctk.CTkLabel(
                row,
                text=date_text,
                font=FONTS["mono"],
                text_color=COLORS["text_muted"],
                anchor="w",
            ).grid(row=0, column=0, padx=10, pady=8, sticky="w")

            # Company
            comp = item.get("company") or "Direct Apply"
            ctk.CTkLabel(
                row,
                text=comp,
                font=FONTS["body_sm"],
                text_color=COLORS["text_primary"],
                anchor="w",
            ).grid(row=0, column=1, padx=10, pady=8, sticky="w")

            # Title
            title = item.get("title") or "Direct URL Application"
            if len(title) > 28:
                title = title[:28] + "..."
            ctk.CTkLabel(
                row,
                text=title,
                font=FONTS["heading_sm"],
                text_color=COLORS["text_primary"],
                anchor="w",
            ).grid(row=0, column=2, padx=10, pady=8, sticky="w")

            # Status Badge
            self._render_status_badge(row, item["status"])

            # Notes
            notes = item.get("notes") or "--"
            if len(notes) > 36:
                notes = notes[:36] + "..."
            ctk.CTkLabel(
                row,
                text=notes,
                font=FONTS["body_sm"],
                text_color=COLORS["text_secondary"],
                anchor="w",
            ).grid(row=0, column=4, padx=10, pady=8, sticky="w")

    def _render_status_badge(self, parent: ctk.CTkFrame, status: str) -> None:
        colors = {
            "SUBMITTED": COLORS["accent_green"],
            "APPLIED": COLORS["accent_green"],
            "FAILED": COLORS["accent_red"],
            "SKIPPED": COLORS["accent_cyan"],
            "REDIRECTED": COLORS["accent_orange"],
            "EXTERNAL_REQUIRED": COLORS["accent_orange"],
            "ERROR": COLORS["accent_red"],
        }
        color = colors.get(status, COLORS["text_muted"])
        badge = ctk.CTkLabel(
            parent,
            text=status,
            font=FONTS["label"],
            text_color="#FFFFFF",
            fg_color=color,
            corner_radius=6,
            width=90,
            height=22,
        )
        badge.grid(row=0, column=3, padx=10, pady=8)

    def _apply_filters(self) -> None:
        if not self.winfo_exists():
            return
        q = self._search_var.get().lower().strip()
        filtered = self._attempts
        if q:
            filtered = [
                x
                for x in filtered
                if (x.get("company") and q in x["company"].lower())
                or (x.get("title") and q in x["title"].lower())
            ]
        self._render_attempts(filtered)

    def refresh(self) -> None:
        """Fetch all attempts from the database."""

        async def _load():
            from core.database import get_database

            db = get_database()
            attempts = await db.get_application_attempts(limit=150)
            self._attempts = attempts
            self.after(0, self._apply_filters)

        self._app.run_async(_load())

    def _update_live_monitor(self) -> None:
        if not self.winfo_exists():
            return

        from services.state_manager import AppState, get_state_manager

        stm = get_state_manager()
        snap = stm.get_snapshot()

        # 1. State/Website details
        app_state = snap.app_state
        self._lbl_live_status.configure(text=app_state.value)
        self._lbl_live_website.configure(text=snap.current_website)
        self._lbl_live_ats.configure(text=snap.current_ats)

        job = snap.current_job
        self._lbl_live_job.configure(
            text=f"{job.title} @ {job.company}" if job else "No Active Job"
        )

        url = snap.current_url
        self._lbl_live_url.configure(
            text=(url[:32] + "...") if url and len(url) > 32 else (url or "Unavailable")
        )

        # 2. Heartbeat & Execution states
        from automation.browser_health import get_execution_state

        exec_state = get_execution_state()

        self._lbl_live_action.configure(text=exec_state.get("browser_action", "none"))
        self._lbl_live_selector.configure(
            text=exec_state.get("playwright_request", "none")
        )
        self._lbl_live_milestone.configure(text=exec_state.get("milestone", "Unknown"))

        # Resume uploads
        try:
            from services.queue_manager import get_application_queue

            q = get_application_queue()
            if q._current_job:
                # check if there was a resume upload attempt
                from core.database import get_database

                db = get_database()

                async def fetch_resume_log():
                    status = await db.get_latest_resume_upload_status(q._current_job.id)
                    if status:
                        self.after(
                            0, lambda s=status: self._lbl_live_resume.configure(text=s)
                        )

                self._app.run_async(fetch_resume_log())
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)

        # Timeline rendering
        self._timeline_box.configure(state="normal")
        self._timeline_box.delete("1.0", "end")

        timeline_entries = []
        if job:
            timeline_entries.append(f"[JOB] Loaded: {job.title} at {job.company}")
        if stm.current_website != "Unavailable":
            timeline_entries.append(
                f"[BROWSER] Navigated to website: {stm.current_website}"
            )
        if stm.current_ats != "Unavailable":
            timeline_entries.append(f"[ATS] System detected: {stm.current_ats}")
        if exec_state.get("milestone") != "Unknown":
            timeline_entries.append(
                f"[STAGE] Milestone reached: {exec_state.get('milestone')}"
            )
        if exec_state.get("browser_action") != "none":
            timeline_entries.append(
                f"[AI] Action executed: {exec_state.get('browser_action')}"
            )
        if app_state == AppState.PAUSED:
            timeline_entries.append(
                "[PAUSED] Waiting for CAPTCHA or user validation..."
            )

        if not timeline_entries:
            timeline_entries.append(
                "[IDLE] Monitor active. Waiting for automation task to begin."
            )

        self._timeline_box.insert("1.0", "\n".join(timeline_entries))
        self._timeline_box.configure(state="disabled")

        # 3. Reload Live Viewport Screenshot
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
                # Resize dynamically to match layout
                ratio = 460 / w
                target_h = int(h * ratio)
                ctk_img = ctk.CTkImage(
                    light_image=img, dark_image=img, size=(460, target_h)
                )
                self._lbl_live_screenshot.configure(image=ctk_img, text="")
            except Exception as e:
                self._lbl_live_screenshot.configure(
                    text=f"Failed to load screenshot: {e}", image=None
                )
        else:
            self._lbl_live_screenshot.configure(
                image=None,
                text="Screenshot will appear here during active browser runs.",
            )

    def _poll_live_state(self) -> None:
        """Poll state frequently to ensure real-time responsiveness."""
        if not self.winfo_exists():
            return
        # Only poll if we are in the live monitor tab
        if self._tabview.get() == "Live Run Monitor":
            self._update_live_monitor()
        self.after(2000, self._poll_live_state)

    def _export_csv(self) -> None:
        async def do_export():
            try:
                from services.job_service import get_job_service

                js = get_job_service()
                _j_csv, a_csv = await js.export_csv()
                from gui.widgets.dialogs import MessageDialog

                self.after(
                    0,
                    lambda: MessageDialog(
                        self,
                        title="Export Success",
                        message=f"Exported successfully!\nApplied CSV: {a_csv}",
                        icon="✅",
                    ),
                )
            except Exception:
                from gui.widgets.dialogs import MessageDialog

                self.after(
                    0,
                    lambda: MessageDialog(
                        self,
                        title="Export Failed",
                        message=f"Error exporting data: {e}",
                        icon="❌",
                    ),
                )

        self._app.run_async(do_export())

    def _open_log(self) -> None:
        try:
            import os
            import sys

            from core.logger import get_log_path

            path = get_log_path()
            if path and path.exists():
                if sys.platform == "win32":
                    os.startfile(str(path))
                else:
                    import subprocess

                    subprocess.run(
                        ["open" if sys.platform == "darwin" else "xdg-open", str(path)]
                    )
        except Exception as e:
            from gui.widgets.dialogs import MessageDialog

            MessageDialog(
                self, title="Error", message=f"Failed to open log file: {e}", icon="❌"
            )

    def on_show(self) -> None:
        self.refresh()
