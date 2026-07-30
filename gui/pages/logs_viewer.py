"""
Logs Viewer page — live scrollable log display with separate categories, filters, search, and download.
"""

from __future__ import annotations

from core.logger import get_logger

logger = get_logger(__name__)

from typing import TYPE_CHECKING

import customtkinter as ctk

from config.constants import COLORS, FONTS
from core.logger import get_log_path

if TYPE_CHECKING:
    from gui.app import App


class LogsViewerPage(ctk.CTkFrame):
    def __init__(self, master, app: App, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_primary"], **kwargs)
        self._app = app
        self._auto_refresh = False
        self._poll_timer_id = None
        self._build()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=32, pady=(24, 0), sticky="ew")

        ctk.CTkLabel(
            header,
            text="Log Console Viewer",
            font=FONTS["heading_xl"],
            text_color=COLORS["text_primary"],
        ).pack(side="left")

        # Clear View
        ctk.CTkButton(
            header,
            text="🗑  Clear View",
            fg_color=COLORS["bg_hover"],
            hover_color=COLORS["accent_red"],
            font=FONTS["body_md"],
            height=38,
            corner_radius=10,
            command=self._clear_view,
        ).pack(side="right")

        # Download / Export
        ctk.CTkButton(
            header,
            text="📤  Download Logs",
            fg_color=COLORS["bg_hover"],
            hover_color=COLORS["accent_primary"],
            font=FONTS["body_md"],
            height=38,
            corner_radius=10,
            command=self._download_logs,
        ).pack(side="right", padx=(0, 10))

        # Filters Bar
        filter_bar = ctk.CTkFrame(
            self,
            fg_color=COLORS["bg_card"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
        )
        filter_bar.grid(row=1, column=0, padx=32, pady=12, sticky="ew")

        # Category Menu
        self._category_var = ctk.StringVar(value="Application")
        ctk.CTkOptionMenu(
            filter_bar,
            variable=self._category_var,
            values=[
                "Application",
                "Browser",
                "Vision",
                "Database",
                "Queue",
                "Recovery",
                "AI",
                "ATS",
                "Errors",
            ],
            fg_color=COLORS["bg_card"],
            button_color=COLORS["accent_primary"],
            width=140,
            height=36,
            command=lambda _: self._load_logs(),
        ).pack(side="left", padx=10, pady=8)

        # Level Menu
        self._level_var = ctk.StringVar(value="ALL")
        ctk.CTkOptionMenu(
            filter_bar,
            variable=self._level_var,
            values=["ALL", "INFO", "WARNING", "ERROR", "DEBUG"],
            fg_color=COLORS["bg_card"],
            button_color=COLORS["accent_primary"],
            width=110,
            height=36,
            command=lambda _: self._load_logs(),
        ).pack(side="left", padx=5, pady=8)

        # Search field
        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._load_logs())
        self._search_entry = ctk.CTkEntry(
            filter_bar,
            placeholder_text="Search log content...",
            textvariable=self._search_var,
            width=180,
            height=36,
            corner_radius=6,
        )
        self._search_entry.pack(side="left", padx=10, pady=8)

        # Auto-refresh
        self._auto_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            filter_bar,
            text="Auto-refresh",
            variable=self._auto_var,
            font=FONTS["body_sm"],
            text_color=COLORS["text_secondary"],
            fg_color=COLORS["accent_primary"],
            command=self._toggle_auto,
        ).pack(side="right", padx=16, pady=8)

        # Refresh button
        ctk.CTkButton(
            filter_bar,
            text="↻ Refresh",
            font=FONTS["body_sm"],
            height=36,
            width=100,
            command=self._load_logs,
        ).pack(side="right", padx=10, pady=8)

        # Log textbox
        log_frame = ctk.CTkFrame(
            self,
            fg_color=COLORS["bg_secondary"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
        )
        log_frame.grid(row=2, column=0, padx=32, pady=(0, 20), sticky="nsew")
        log_frame.grid_rowconfigure(0, weight=1)
        log_frame.grid_columnconfigure(0, weight=1)

        self._log_box = ctk.CTkTextbox(
            log_frame,
            font=FONTS["mono"],
            fg_color=COLORS["bg_secondary"],
            text_color=COLORS["text_primary"],
            wrap="word",
            state="disabled",
        )
        self._log_box.grid(row=0, column=0, padx=4, pady=4, sticky="nsew")

        # Status
        self._status_lbl = ctk.CTkLabel(
            self,
            text="",
            font=FONTS["body_sm"],
            text_color=COLORS["text_muted"],
        )
        self._status_lbl.grid(row=3, column=0, padx=32, pady=(0, 8), sticky="w")

    def _load_logs(self) -> None:
        log_path = get_log_path()
        if not log_path or not log_path.exists():
            self._set_text("Log file not found yet.")
            return

        try:
            content = log_path.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()

            # Parse and filter dynamically
            category = self._category_var.get()
            level_filter = self._level_var.get()
            search_query = self._search_var.get().lower().strip()

            filtered_lines = []
            for line in lines:
                parts = line.split(" | ")
                if len(parts) < 4:
                    # Non-formatted traceback line, append to previous if matching category
                    if filtered_lines:
                        filtered_lines.append(line)
                    continue

                lvl = parts[1].strip()
                logger_name = parts[2].strip()
                parts[3].strip()

                # Level filter
                if level_filter != "ALL" and level_filter != lvl:
                    continue

                # Search query
                if search_query and search_query not in line.lower():
                    continue

                # Category filter
                line_cat = "Application"
                if lvl in ("ERROR", "CRITICAL"):
                    line_cat = "Errors"
                elif any(
                    x in logger_name
                    for x in (
                        "browser_manager",
                        "browser_session_pool",
                        "cdp_connector",
                    )
                ):
                    line_cat = "Browser"
                elif "vision_engine" in logger_name:
                    line_cat = "Vision"
                elif "database" in logger_name:
                    line_cat = "Database"
                elif "queue_manager" in logger_name:
                    line_cat = "Queue"
                elif "browser_health" in logger_name:
                    line_cat = "Recovery"
                elif any(
                    x in logger_name
                    for x in (
                        "smart_ai",
                        "smart_locator",
                        "smart_click",
                        "smart_input",
                        "form_intelligence",
                        "resume_intelligence",
                    )
                ):
                    line_cat = "AI"
                elif any(
                    x in logger_name for x in ("website_modules", "website_strategies")
                ):
                    line_cat = "ATS"

                # Check match
                if category == line_cat:
                    filtered_lines.append(line)

            # Show last 500 lines of filtered results
            display = "\n".join(filtered_lines[-500:])
            self._set_text(display)
            self._status_lbl.configure(
                text=f"Console: {category} logs  •  {len(filtered_lines)} matches"
            )
            self._log_box.see("end")
        except Exception as exc:
            self._set_text(f"Error reading log: {exc}")

    def _set_text(self, text: str) -> None:
        self._log_box.configure(state="normal")
        self._log_box.delete("1.0", "end")
        self._log_box.insert("1.0", text)
        self._log_box.configure(state="disabled")

    def _clear_view(self) -> None:
        self._set_text("")
        self._status_lbl.configure(text="View cleared")

    def _download_logs(self) -> None:
        # Prompt to save file
        from tkinter import filedialog

        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="Export Categorized Logs",
        )
        if path:
            try:
                log_box_content = self._log_box.get("1.0", "end")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(log_box_content)
                self._status_lbl.configure(text=f"Logs exported to {path}")
            except Exception as e:
                self._status_lbl.configure(text=f"Export failed: {e}")

    def _toggle_auto(self) -> None:
        if self._auto_var.get():
            self._auto_refresh = True
            if self._poll_timer_id:
                try:
                    self.after_cancel(self._poll_timer_id)
                except Exception as _exc:
                    logger.debug("Suppressed: %s", _exc)
            self._poll()
        else:
            self._auto_refresh = False
            if self._poll_timer_id:
                try:
                    self.after_cancel(self._poll_timer_id)
                except Exception as _exc:
                    logger.debug("Suppressed: %s", _exc)
                self._poll_timer_id = None

    def _poll(self) -> None:
        if not self._auto_refresh or not self.winfo_exists():
            return
        self._load_logs()
        self._poll_timer_id = self.after(3000, self._poll)

    def on_show(self) -> None:
        self._load_logs()
        if self._auto_var.get():
            self._auto_refresh = True
            if self._poll_timer_id:
                try:
                    self.after_cancel(self._poll_timer_id)
                except Exception as _exc:
                    logger.debug("Suppressed: %s", _exc)
            self._poll()

    def on_hide(self) -> None:
        """Called when navigating away from this page."""
        self._auto_refresh = False
        if self._poll_timer_id:
            try:
                self.after_cancel(self._poll_timer_id)
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)
            self._poll_timer_id = None

    def destroy(self) -> None:
        """Clean up timers when widget is destroyed."""
        self.on_hide()
        super().destroy()
