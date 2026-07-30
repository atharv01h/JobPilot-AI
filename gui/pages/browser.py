"""
Browser Page — manage Brave browser automation session, CDP connection, cookies, and profiles.
Uses StateManager to display live tab, URL, cookies, process stats, and screenshot.
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


class BrowserPage(ctk.CTkFrame):
    def __init__(self, master, app: App, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_primary"], **kwargs)
        self._app = app
        self._build()

        # Subscribe to StateManager
        from services.state_manager import get_state_manager

        get_state_manager().register_listener(self._on_state_changed)

    def destroy(self) -> None:
        try:
            from services.state_manager import get_state_manager

            get_state_manager().unregister_listener(self._on_state_changed)
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)
        super().destroy()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ── Header ────────────────────────────────────────────────────────────
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=32, pady=(24, 0), sticky="ew")

        ctk.CTkLabel(
            header,
            text="Browser Controller",
            font=FONTS["heading_xl"],
            text_color=COLORS["text_primary"],
        ).pack(side="left")

        # Action Buttons frame
        actions_frame = ctk.CTkFrame(header, fg_color="transparent")
        actions_frame.pack(side="right")

        ctk.CTkButton(
            actions_frame,
            text="🔄  Restart Browser",
            fg_color=COLORS["accent_red"],
            hover_color="#B02A2A",
            font=FONTS["body_md"],
            height=38,
            corner_radius=10,
            command=self._restart_browser,
        ).pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            actions_frame,
            text="🌐  Reconnect Browser",
            fg_color=COLORS["accent_primary"],
            hover_color=COLORS["accent_secondary"],
            font=FONTS["body_md"],
            height=38,
            corner_radius=10,
            command=self._reconnect_browser,
        ).pack(side="right")

        # Scrollable Configuration
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.grid(row=1, column=0, padx=32, pady=16, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)

        # ── CDP Status & Browser Telemetry Card ─────────────────────────────
        card_conn = ctk.CTkFrame(
            scroll,
            fg_color=COLORS["bg_card"],
            corner_radius=16,
            border_width=1,
            border_color=COLORS["border"],
        )
        card_conn.pack(fill="x", pady=8)
        card_conn.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            card_conn,
            text="Chrome DevTools Protocol (CDP) Status",
            font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"],
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, padx=20, pady=(16, 8), sticky="w")

        self._lbl_cdp = self._create_row(card_conn, 1, "CDP Connection:")
        self._lbl_pid = self._create_row(card_conn, 2, "Brave Process PID:")
        self._lbl_browser_mem = self._create_row(card_conn, 3, "Browser Memory:")
        self._lbl_path = self._create_row(card_conn, 4, "Brave Binary Path:")
        self._lbl_profile = self._create_row(card_conn, 5, "Active Profile Path:")

        # ── Active Tab & Live Session Info ──────────────────────────────────
        card_active = ctk.CTkFrame(
            scroll,
            fg_color=COLORS["bg_card"],
            corner_radius=16,
            border_width=1,
            border_color=COLORS["border"],
        )
        card_active.pack(fill="x", pady=8)
        card_active.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            card_active,
            text="Active Browser Tab Info",
            font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"],
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, padx=20, pady=(16, 8), sticky="w")

        self._lbl_tab = self._create_row(card_active, 1, "Current Tab Title:")
        self._lbl_url = self._create_row(card_active, 2, "Current Tab URL:")
        self._lbl_cookies = self._create_row(card_active, 3, "Stored Cookies Count:")

        # ── Stored Session Cookies status ───────────────────────────────────
        card_cookies = ctk.CTkFrame(
            scroll,
            fg_color=COLORS["bg_card"],
            corner_radius=16,
            border_width=1,
            border_color=COLORS["border"],
        )
        card_cookies.pack(fill="x", pady=8)
        card_cookies.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            card_cookies,
            text="Stored Portal Session Statuses",
            font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"],
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, padx=20, pady=(16, 8), sticky="w")

        self._lbl_li = self._create_row(card_cookies, 1, "LinkedIn Session:")
        self._lbl_nk = self._create_row(card_cookies, 2, "Naukri Session:")
        self._lbl_id = self._create_row(card_cookies, 3, "Indeed Session:")
        self._lbl_gd = self._create_row(card_cookies, 4, "Glassdoor Session:")

        # ── Live Screenshot view ────────────────────────────────────────────
        card_screenshot = ctk.CTkFrame(
            scroll,
            fg_color=COLORS["bg_card"],
            corner_radius=16,
            border_width=1,
            border_color=COLORS["border"],
        )
        card_screenshot.pack(fill="x", pady=8)
        card_screenshot.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card_screenshot,
            text="Live Browser View / Screenshot",
            font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"],
            anchor="w",
        ).pack(padx=20, pady=(16, 8), anchor="w")

        self._lbl_screenshot = ctk.CTkLabel(
            card_screenshot,
            text="No screenshot available",
            font=FONTS["body_sm"],
            text_color=COLORS["text_muted"],
        )
        self._lbl_screenshot.pack(padx=20, pady=(8, 20))

        # Initial populate
        self._update_telemetry()

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
            anchor="e",
        )
        val_lbl.grid(row=row, column=1, padx=20, pady=8, sticky="e")
        return val_lbl

    def _reconnect_browser(self) -> None:
        async def run():
            from automation.browser_session_pool import get_browser_session_pool

            bm = get_browser_session_pool()
            await bm.close()
            await bm.reconnect()
            self._update_telemetry()

        self._app.run_async(run())

    def _restart_browser(self) -> None:
        """Terminates all Brave processes and starts a fresh debug session."""

        async def run():
            from automation.browser_session_pool import get_browser_session_pool
            from automation.cdp_connector import kill_brave

            pool = get_browser_session_pool()
            await pool.close()
            await asyncio.to_thread(kill_brave)
            await pool.reconnect()
            self._update_telemetry()

        self._app.run_async(run())

    def _on_state_changed(self) -> None:
        if self.winfo_exists():
            self._update_telemetry()

    def _update_telemetry(self) -> None:
        from config.constants import BRAVE_EXE_PATH
        from services.session_manager import get_session_manager
        from services.state_manager import get_state_manager

        stm = get_state_manager()
        sm = get_session_manager()

        cdp_status = stm.browser_status
        self._lbl_cdp.configure(text=cdp_status)
        if "Connected" in cdp_status:
            self._lbl_cdp.configure(text_color=COLORS["accent_green"])
        else:
            self._lbl_cdp.configure(text_color=COLORS["accent_red"])

        # Parse telemetry stats: "{brave_pid}|{brave_mem}|{cpu}|{mem}|{gpu}"
        telemetry_raw = stm.live_progress_text
        pid = "Unavailable"
        mem = "Unavailable"
        if telemetry_raw and "|" in telemetry_raw:
            parts = telemetry_raw.split("|")
            if len(parts) >= 2:
                pid = parts[0]
                mem = parts[1]

        self._lbl_pid.configure(text=pid)
        self._lbl_browser_mem.configure(text=mem)
        self._lbl_path.configure(text=BRAVE_EXE_PATH)
        self._lbl_profile.configure(text=sm.get_profile_info())

        # Live tab metrics
        self._lbl_tab.configure(
            text=stm.current_tab if stm.current_tab else "Unavailable"
        )

        url_text = stm.current_url
        if len(url_text) > 60:
            url_text = url_text[:60] + "..."
        self._lbl_url.configure(text=url_text)
        self._lbl_cookies.configure(text=f"{stm.cookies_count} active")

        # Stored sessions
        self._lbl_li.configure(text=sm.get_status("linkedin").get("status", "Unknown"))
        self._lbl_nk.configure(text=sm.get_status("naukri").get("status", "Unknown"))
        self._lbl_id.configure(text=sm.get_status("indeed").get("status", "Unknown"))
        self._lbl_gd.configure(text=sm.get_status("glassdoor").get("status", "Unknown"))

        # Update screenshot
        screenshot_path = "logs/watchdog_diagnostic.png"
        if os.path.exists(screenshot_path):
            try:
                img = Image.open(screenshot_path)
                w, h = img.size
                ratio = 520 / w
                target_h = int(h * ratio)
                ctk_img = ctk.CTkImage(
                    light_image=img, dark_image=img, size=(520, target_h)
                )
                self._lbl_screenshot.configure(image=ctk_img, text="")
            except Exception as e:
                self._lbl_screenshot.configure(
                    text=f"Failed to load screenshot: {e}", image=None
                )
        else:
            self._lbl_screenshot.configure(
                text="Screenshot will appear here during active browser runs",
                image=None,
            )

    def on_show(self) -> None:
        self._update_telemetry()
