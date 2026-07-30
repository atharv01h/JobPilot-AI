"""
Session Manager page.
Displays login session status for LinkedIn, Naukri, Indeed, Glassdoor, and Gmail.
Provides Re-login (manual Chromium popup), Check Status, and Reset Browser Profile buttons.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import customtkinter as ctk

from config.constants import COLORS, FONTS
from services.auto_login_service import SITE_LOGIN_URLS
from services.session_manager import get_session_manager

if TYPE_CHECKING:
    from gui.app import App


class SessionManagerPage(ctk.CTkFrame):
    def __init__(self, master, app: App, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_primary"], **kwargs)
        self._app = app
        self._site_rows: dict[str, dict] = {}
        self._is_checking = False
        self._build()
        from services.session_manager import get_session_manager

        get_session_manager().on_status_updated.append(
            lambda: self.after(0, self._update_ui)
        )

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # ── Header ────────────────────────────────────────────────────────────
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=32, pady=(28, 0), sticky="ew")

        ctk.CTkLabel(
            header,
            text="Session Manager",
            font=FONTS["heading_xl"],
            text_color=COLORS["text_primary"],
        ).pack(side="left")

        # Global Action Buttons in Header
        actions_frame = ctk.CTkFrame(header, fg_color="transparent")
        actions_frame.pack(side="right")

        self._check_all_btn = ctk.CTkButton(
            actions_frame,
            text="🔍  Check All Statuses",
            fg_color=COLORS["accent_primary"],
            hover_color=COLORS["accent_secondary"],
            font=FONTS["heading_sm"],
            height=38,
            width=180,
            corner_radius=10,
            command=self._check_all_statuses,
        )
        self._check_all_btn.pack(side="left", padx=6)

        ctk.CTkLabel(
            self,
            text="Verify browser cookies, active login sessions, and perform manual/automatic authentication.",
            font=FONTS["body_md"],
            text_color=COLORS["text_muted"],
            anchor="w",
        ).grid(row=1, column=0, padx=32, pady=(4, 20), sticky="w")

        # ── Main Content scrollable ───────────────────────────────────────────
        self._scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._scroll.grid(row=2, column=0, padx=32, pady=(0, 20), sticky="nsew")
        self._scroll.grid_columnconfigure(0, weight=1)

        # Build list of sites
        sites_config = [
            ("linkedin", "LinkedIn", COLORS["accent_primary"]),
            ("naukri", "Naukri", "#3D85C8"),
            ("indeed", "Indeed", COLORS["accent_orange"]),
            ("glassdoor", "Glassdoor", COLORS["accent_green"]),
            ("foundit", "Foundit", COLORS["accent_cyan"]),
            ("gmail", "Gmail", COLORS["accent_red"]),
        ]

        row = 0
        for site_key, site_name, badge_color in sites_config:
            card = ctk.CTkFrame(
                self._scroll,
                fg_color=COLORS["bg_card"],
                corner_radius=12,
                border_width=1,
                border_color=COLORS["border"],
            )
            card.grid(row=row, column=0, padx=4, pady=6, sticky="ew")
            card.grid_columnconfigure(1, weight=1)  # Site badge / name
            card.grid_columnconfigure(2, weight=1)  # Status indicator
            card.grid_columnconfigure(3, weight=1)  # Last checked / login dates
            card.grid_columnconfigure(4, weight=0)  # Action buttons
            row += 1

            # Site Badge + Title
            badge_frame = ctk.CTkFrame(card, fg_color="transparent")
            badge_frame.grid(row=0, column=0, padx=16, pady=16, sticky="w")

            ctk.CTkLabel(
                badge_frame,
                text=f"  {site_name}  ",
                font=FONTS["label"],
                fg_color=badge_color,
                text_color="#FFFFFF",
                corner_radius=6,
            ).pack(side="left")

            # Status Badge
            status_badge = ctk.CTkLabel(
                card,
                text="Checking...",
                font=FONTS["label"],
                text_color="#FFFFFF",
                fg_color=COLORS["text_muted"],
                width=110,
                height=26,
                corner_radius=6,
            )
            status_badge.grid(row=0, column=2, padx=16, pady=16, sticky="w")

            # Date information
            dates_frame = ctk.CTkFrame(card, fg_color="transparent")
            dates_frame.grid(row=0, column=3, padx=16, pady=16, sticky="w")

            last_checked_lbl = ctk.CTkLabel(
                dates_frame,
                text="Last Checked: --",
                font=FONTS["body_sm"],
                text_color=COLORS["text_secondary"],
                anchor="w",
            )
            last_checked_lbl.pack(anchor="w")

            last_login_lbl = ctk.CTkLabel(
                dates_frame,
                text="Last Login: --",
                font=FONTS["body_sm"],
                text_color=COLORS["text_secondary"],
                anchor="w",
            )
            last_login_lbl.pack(anchor="w")

            # Actions buttons frame
            btn_frame = ctk.CTkFrame(card, fg_color="transparent")
            btn_frame.grid(row=0, column=4, padx=16, pady=16, sticky="e")

            re_login_btn = ctk.CTkButton(
                btn_frame,
                text="🔗  Re-login",
                fg_color=COLORS["bg_hover"],
                hover_color=COLORS["accent_primary"],
                font=FONTS["body_sm"],
                height=32,
                width=100,
                corner_radius=8,
                command=lambda s=site_key: self._re_login(s),
            )
            re_login_btn.pack(side="left", padx=4)

            check_btn = ctk.CTkButton(
                btn_frame,
                text="↻ Check",
                fg_color=COLORS["bg_hover"],
                hover_color=COLORS["accent_cyan"],
                font=FONTS["body_sm"],
                height=32,
                width=80,
                corner_radius=8,
                command=lambda s=site_key: self._check_single(s),
            )
            check_btn.pack(side="left", padx=4)

            # Store widget references
            self._site_rows[site_key] = {
                "status_badge": status_badge,
                "last_checked_lbl": last_checked_lbl,
                "last_login_lbl": last_login_lbl,
                "re_login_btn": re_login_btn,
                "check_btn": check_btn,
            }

        # ── Footer Utilities ──────────────────────────────────────────────────
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=3, column=0, padx=32, pady=(10, 20), sticky="ew")

        ctk.CTkLabel(
            footer,
            text="💡 Keep browser sessions persistent to run uninterrupted automations.",
            font=FONTS["body_sm"],
            text_color=COLORS["text_muted"],
        ).pack(side="left")

        self._reset_btn = ctk.CTkButton(
            footer,
            text="⚠️ Reset Browser Profile",
            fg_color=COLORS["bg_hover"],
            hover_color=COLORS["accent_red"],
            text_color=COLORS["accent_red"],
            font=FONTS["body_sm"],
            height=34,
            width=180,
            corner_radius=8,
            command=self._reset_browser_profile,
        )
        self._reset_btn.pack(side="right")

    def on_show(self) -> None:
        """Called when navigating to this page."""
        self._update_ui()
        # Auto check if status is currently "Unknown"
        sm = get_session_manager()
        has_unknown = any(
            sm.get_status(site)["status"] == "Unknown" for site in self._site_rows
        )
        if has_unknown and not self._is_checking:
            self._check_all_statuses()

    def _update_ui(self) -> None:
        """Read statuses from SessionManager and update badges/labels."""
        sm = get_session_manager()
        for site_key, widgets in self._site_rows.items():
            info = sm.get_status(site_key)
            status = info.get("status", "Unknown")
            checked = info.get("last_checked", "")
            login = info.get("last_login", "")

            # Set status text and badge color
            widgets["status_badge"].configure(text=status)
            if status == "Logged In":
                widgets["status_badge"].configure(fg_color=COLORS["accent_green"])
            elif status == "Logged Out":
                widgets["status_badge"].configure(fg_color=COLORS["accent_red"])
            elif status == "Checking..." or status == "Busy":
                widgets["status_badge"].configure(fg_color=COLORS["accent_orange"])
            else:
                widgets["status_badge"].configure(fg_color=COLORS["text_muted"])

            # Format times
            checked_str = self._format_date(checked)
            login_str = self._format_date(login)
            widgets["last_checked_lbl"].configure(text=f"Last Checked: {checked_str}")
            widgets["last_login_lbl"].configure(text=f"Last Login: {login_str}")

    def _format_date(self, iso_str: str) -> str:
        if not iso_str:
            return "--"
        try:
            dt = datetime.fromisoformat(iso_str)
            return dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return "--"

    def _check_single(self, site: str) -> None:
        """Trigger background status check for a single site."""
        if self._is_checking:
            return

        async def _run():
            self._is_checking = True
            self.after(0, self._set_checking_state)
            sm = get_session_manager()
            await sm.check_site_status(site)
            self._is_checking = False
            self.after(0, self._clear_checking_state)

        self._app.run_async(_run())

    def _check_all_statuses(self) -> None:
        """Trigger background status check for all sites sequentially."""
        if self._is_checking:
            return

        async def _run():
            self._is_checking = True
            self.after(0, self._set_checking_state)
            sm = get_session_manager()
            await sm.check_all_sites()
            self._is_checking = False
            self.after(0, self._clear_checking_state)

        self._app.run_async(_run())

    def _set_checking_state(self) -> None:
        self._check_all_btn.configure(state="disabled", text="🔍 Checking...")
        for widgets in self._site_rows.values():
            widgets["check_btn"].configure(state="disabled")
            widgets["re_login_btn"].configure(state="disabled")
        self._update_ui()

    def _clear_checking_state(self) -> None:
        self._check_all_btn.configure(state="normal", text="🔍  Check All Statuses")
        for widgets in self._site_rows.values():
            widgets["check_btn"].configure(state="normal")
            widgets["re_login_btn"].configure(state="normal")
        self._update_ui()

    def _re_login(self, site: str) -> None:
        """Launch manual login subprocess context and wait for it."""
        if self._is_checking:
            return

        from automation.browser_manager import get_browser_manager

        # Resolve login url
        login_url = SITE_LOGIN_URLS.get(site, [""])[0]
        if not login_url.startswith("http"):
            # Gmail uses accounts.google.com
            if site == "gmail":
                login_url = "https://accounts.google.com/"
            else:
                login_url = f"https://www.{site}.com/login"

        async def _run():
            self._is_checking = True
            self.after(0, self._set_checking_state)
            bm = get_browser_manager()
            # This opens browser and waits for closing
            await bm.open_login_session_async(login_url)
            # Recheck status immediately
            sm = get_session_manager()
            await sm.check_site_status(site)
            self._is_checking = False
            self.after(0, self._clear_checking_state)

        self._app.run_async(_run())

    def _reset_browser_profile(self) -> None:
        """Clear all persistent cookies, login state files and cached statuses."""
        from gui.widgets.dialogs import ConfirmationDialog

        def on_confirm():
            from automation.browser_manager import get_browser_manager

            get_browser_manager().clear_sessions()
            self._update_ui()

        ConfirmationDialog(
            self,
            title="Reset Browser Profile",
            message=(
                "Are you sure you want to reset your browser profile?\n\n"
                "This will permanently delete all saved cookies, login sessions, "
                "local storage, and credentials cached. You will need to log in "
                "again to all sites."
            ),
            on_confirm=on_confirm,
        )
