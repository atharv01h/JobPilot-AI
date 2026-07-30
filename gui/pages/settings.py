"""
Settings page — configure API key, paths, filters, and scheduler.
"""

from __future__ import annotations

from core.logger import get_logger

logger = get_logger(__name__)

import tkinter.filedialog as fd
from typing import TYPE_CHECKING

import customtkinter as ctk

from config.constants import COLORS, FONTS, SCHEDULER_OPTIONS
from config.settings import get_settings

if TYPE_CHECKING:
    from gui.app import App


class SettingsPage(ctk.CTkFrame):
    def __init__(self, master, app: App, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_primary"], **kwargs)
        self._app = app
        self._after_ids = set()
        self._build()

    def after(self, delay_ms: int, callback=None, *args) -> str:
        if not self.winfo_exists():
            return ""
        aid = super().after(delay_ms, callback, *args)
        self._after_ids.add(aid)
        return aid

    def destroy(self) -> None:
        for aid in list(self._after_ids):
            try:
                self.after_cancel(aid)
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)
        self._after_ids.clear()
        super().destroy()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=32, pady=(28, 0), sticky="ew")
        ctk.CTkLabel(
            header,
            text="Settings",
            font=FONTS["heading_xl"],
            text_color=COLORS["text_primary"],
        ).pack(side="left")
        ctk.CTkButton(
            header,
            text="💾  Save Settings",
            fg_color=COLORS["accent_primary"],
            hover_color=COLORS["accent_secondary"],
            font=FONTS["heading_sm"],
            height=42,
            width=160,
            corner_radius=12,
            command=self._save,
        ).pack(side="right")

        ctk.CTkLabel(
            self,
            text="Configure your job assistant preferences",
            font=FONTS["body_md"],
            text_color=COLORS["text_muted"],
            anchor="w",
        ).grid(row=1, column=0, padx=32, pady=(4, 16), sticky="w")

        # Scrollable content
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.grid(row=2, column=0, padx=32, pady=(0, 28), sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)

        row = 0

        # ── NVIDIA NIM ────────────────────────────────────────────────────────
        row = self._section(scroll, row, "🧠  NVIDIA NIM Configuration")
        self._api_key_entry, row = self._entry_row(
            scroll,
            row,
            "API Key",
            placeholder="nvapi-…",
            show="*",
        )
        self._model_entry, row = self._entry_row(
            scroll,
            row,
            "Model",
            placeholder="nvidia/nemotron-3-super-120b-a12b",
        )

        # ── File Paths ────────────────────────────────────────────────────────
        row = self._section(scroll, row, "📁  File Paths")
        self._resume_entry, row = self._entry_row_with_browse(
            scroll,
            row,
            "Resume PDF Path",
            "pdf",
        )
        self._form_entry, row = self._entry_row_with_browse(
            scroll,
            row,
            "Form Data Path (form.txt)",
            "txt",
        )
        self._db_entry, row = self._entry_row(
            scroll,
            row,
            "Database Path (jobs.db)",
        )

        # ── Scheduler ─────────────────────────────────────────────────────────
        row = self._section(scroll, row, "⏰  Search Scheduler")
        ctk.CTkLabel(
            scroll,
            text="Auto-search Interval",
            font=FONTS["label"],
            text_color=COLORS["text_secondary"],
            anchor="w",
        ).grid(row=row, column=0, padx=4, pady=(8, 4), sticky="w")
        row += 1

        self._scheduler_var = ctk.StringVar(value="Manual")
        scheduler_menu = ctk.CTkOptionMenu(
            scroll,
            variable=self._scheduler_var,
            values=SCHEDULER_OPTIONS,
            fg_color=COLORS["bg_card"],
            button_color=COLORS["accent_primary"],
            button_hover_color=COLORS["accent_secondary"],
            dropdown_fg_color=COLORS["bg_card"],
            font=FONTS["body_md"],
            width=240,
            height=38,
            command=lambda _: self._save(),
        )
        scheduler_menu.grid(row=row, column=0, padx=4, pady=(0, 8), sticky="w")
        row += 1

        # ── Notifications ─────────────────────────────────────────────────────
        row = self._section(scroll, row, "🔔  Notifications")
        self._notif_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            scroll,
            text="Enable Desktop Notifications",
            variable=self._notif_var,
            font=FONTS["body_md"],
            text_color=COLORS["text_primary"],
            fg_color=COLORS["accent_primary"],
            hover_color=COLORS["accent_secondary"],
            command=self._save,
        ).grid(row=row, column=0, padx=4, pady=8, sticky="w")
        row += 1

        # ── Login Credentials (Automatic Login) ─────────────────────────────
        row = self._section(scroll, row, "\U0001f511  Login Credentials (Auto-Login)")

        ctk.CTkLabel(
            scroll,
            text=(
                "Enter your login credentials for each job site below.\n"
                "The assistant will log in automatically whenever needed — "
                "you will NEVER be asked to log in manually."
            ),
            font=FONTS["body_sm"],
            text_color=COLORS["text_secondary"],
            justify="left",
            anchor="w",
            wraplength=700,
        ).grid(row=row, column=0, padx=4, pady=(0, 12), sticky="w")
        row += 1

        # Credential card for each site
        self._cred_entries: dict = {}  # site -> {"email": Entry, "pass": Entry}

        SITES_CFG = [
            ("linkedin", "LinkedIn", COLORS["accent_primary"]),
            ("naukri", "Naukri", "#3D85C8"),
            ("indeed", "Indeed", COLORS["accent_orange"]),
            ("glassdoor", "Glassdoor", COLORS["accent_green"]),
            ("foundit", "Foundit", COLORS["accent_cyan"]),
            ("gmail", "Gmail", COLORS["accent_red"]),
        ]

        for site_key, site_name, color in SITES_CFG:
            card = ctk.CTkFrame(
                scroll,
                fg_color=COLORS["bg_card"],
                corner_radius=12,
                border_width=1,
                border_color=COLORS["border"],
            )
            card.grid(row=row, column=0, padx=4, pady=(0, 8), sticky="ew")
            card.grid_columnconfigure((1, 3), weight=1)
            row += 1

            # Site badge
            ctk.CTkLabel(
                card,
                text=f"  {site_name}  ",
                font=FONTS["label"],
                fg_color=color,
                text_color="#FFFFFF",
                corner_radius=6,
            ).grid(row=0, column=0, padx=(12, 16), pady=12, sticky="w")

            # Email
            ctk.CTkLabel(
                card,
                text="Email",
                font=FONTS["label"],
                text_color=COLORS["text_secondary"],
            ).grid(row=0, column=1, padx=(0, 6), pady=12, sticky="e")

            email_entry = ctk.CTkEntry(
                card,
                font=FONTS["body_md"],
                fg_color=COLORS["bg_secondary"],
                border_color=COLORS["border"],
                text_color=COLORS["text_primary"],
                placeholder_text="your@email.com",
                height=34,
                corner_radius=8,
            )
            email_entry.grid(row=0, column=2, padx=(0, 16), pady=12, sticky="ew")
            card.grid_columnconfigure(2, weight=1)

            # Password
            ctk.CTkLabel(
                card,
                text="Password",
                font=FONTS["label"],
                text_color=COLORS["text_secondary"],
            ).grid(row=0, column=3, padx=(0, 6), pady=12, sticky="e")

            pass_entry = ctk.CTkEntry(
                card,
                font=FONTS["body_md"],
                fg_color=COLORS["bg_secondary"],
                border_color=COLORS["border"],
                text_color=COLORS["text_primary"],
                placeholder_text="password",
                show="*",
                height=34,
                corner_radius=8,
            )
            pass_entry.grid(row=0, column=4, padx=(0, 12), pady=12, sticky="ew")
            card.grid_columnconfigure(4, weight=1)

            # Bind FocusOut to save credentials immediately
            email_entry.bind("<FocusOut>", lambda _: self._save_credentials())
            pass_entry.bind("<FocusOut>", lambda _: self._save_credentials())

            # Status dot
            self._cred_entries[site_key] = {
                "email": email_entry,
                "pass": pass_entry,
            }

        # Save Credentials button
        cred_btn_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        cred_btn_frame.grid(row=row, column=0, padx=4, pady=(4, 4), sticky="w")
        row += 1

        ctk.CTkButton(
            cred_btn_frame,
            text="\U0001f4be  Save Credentials",
            fg_color=COLORS["accent_primary"],
            hover_color=COLORS["accent_secondary"],
            font=FONTS["body_md"],
            width=180,
            height=38,
            corner_radius=10,
            command=self._save_credentials,
        ).pack(side="left")

        ctk.CTkLabel(
            cred_btn_frame,
            text="  Stored locally on this machine only",
            font=FONTS["body_sm"],
            text_color=COLORS["text_muted"],
        ).pack(side="left", padx=(10, 0))

        # Reset browser profile utility
        ctk.CTkButton(
            scroll,
            text="Reset Browser Profile",
            fg_color=COLORS["bg_hover"],
            hover_color=COLORS["accent_red"],
            text_color=COLORS["accent_red"],
            font=FONTS["body_sm"],
            width=220,
            height=32,
            corner_radius=8,
            command=self._reset_browser_profile,
        ).grid(row=row, column=0, padx=4, pady=(0, 2), sticky="w")
        row += 1

        ctk.CTkLabel(
            scroll,
            text="* Note: This will require re-login to all sites.",
            font=FONTS["body_sm"],
            text_color=COLORS["text_muted"],
        ).grid(row=row, column=0, padx=8, pady=(0, 8), sticky="w")
        row += 1

        # ── Status message ────────────────────────────────────────────────────
        self._status_lbl = ctk.CTkLabel(
            scroll,
            text="",
            font=FONTS["body_md"],
            text_color=COLORS["accent_green"],
        )
        self._status_lbl.grid(row=row, column=0, padx=4, pady=16, sticky="w")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _section(self, parent, row: int, title: str) -> int:
        if row > 0:
            ctk.CTkFrame(parent, height=1, fg_color=COLORS["border"]).grid(
                row=row, column=0, padx=4, pady=(16, 0), sticky="ew"
            )
            row += 1
        ctk.CTkLabel(
            parent,
            text=title,
            font=FONTS["heading_sm"],
            text_color=COLORS["text_secondary"],
            anchor="w",
        ).grid(row=row, column=0, padx=4, pady=(12, 4), sticky="w")
        return row + 1

    def _entry_row(
        self,
        parent,
        row: int,
        label: str,
        placeholder: str = "",
        show: str = "",
    ):
        ctk.CTkLabel(
            parent,
            text=label,
            font=FONTS["label"],
            text_color=COLORS["text_secondary"],
            anchor="w",
        ).grid(row=row, column=0, padx=4, pady=(8, 2), sticky="w")
        row += 1
        entry = ctk.CTkEntry(
            parent,
            font=FONTS["body_md"],
            fg_color=COLORS["bg_card"],
            border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            placeholder_text=placeholder,
            height=38,
            corner_radius=8,
            show=show,
        )
        entry.grid(row=row, column=0, padx=4, pady=(0, 4), sticky="ew")
        entry.bind("<FocusOut>", lambda _: self._save())
        return entry, row + 1

    def _entry_row_with_browse(self, parent, row: int, label: str, ext: str):
        ctk.CTkLabel(
            parent,
            text=label,
            font=FONTS["label"],
            text_color=COLORS["text_secondary"],
            anchor="w",
        ).grid(row=row, column=0, padx=4, pady=(8, 2), sticky="w")
        row += 1

        row_frame = ctk.CTkFrame(parent, fg_color="transparent")
        row_frame.grid(row=row, column=0, padx=4, pady=(0, 4), sticky="ew")
        row_frame.grid_columnconfigure(0, weight=1)

        entry = ctk.CTkEntry(
            row_frame,
            font=FONTS["body_md"],
            fg_color=COLORS["bg_card"],
            border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            height=38,
            corner_radius=8,
        )
        entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        entry.bind("<FocusOut>", lambda _: self._save())

        ctk.CTkButton(
            row_frame,
            text="Browse",
            fg_color=COLORS["bg_hover"],
            hover_color=COLORS["accent_primary"],
            font=FONTS["body_sm"],
            height=38,
            width=80,
            corner_radius=8,
            command=lambda e=entry, x=ext: self._browse(e, x),
        ).grid(row=0, column=1)

        return entry, row + 1

    def _browse(self, entry: ctk.CTkEntry, ext: str) -> None:
        if ext == "pdf":
            filetypes = [("PDF files", "*.pdf")]
        else:
            filetypes = [("Text files", "*.txt"), ("All files", "*.*")]
        path = fd.askopenfilename(filetypes=filetypes)
        if path:
            entry.delete(0, "end")
            entry.insert(0, path)
            self._save()

    # ── Load / Save ───────────────────────────────────────────────────────────

    def on_show(self) -> None:
        settings = get_settings()
        self._api_key_entry.delete(0, "end")
        self._api_key_entry.insert(0, settings.llm_api_key)
        self._model_entry.delete(0, "end")
        self._model_entry.insert(0, settings.llm_model)
        self._resume_entry.delete(0, "end")
        self._resume_entry.insert(0, settings.resume_path)
        self._form_entry.delete(0, "end")
        self._form_entry.insert(0, settings.profile_path)
        self._db_entry.delete(0, "end")
        self._db_entry.insert(0, settings.db_path)
        self._scheduler_var.set(settings.scheduler_interval)
        self._notif_var.set(settings.desktop_notifications_enabled)
        self._status_lbl.configure(text="")

        # Load saved credentials into credential fields
        from services.auto_login_service import get_auto_login_service

        svc = get_auto_login_service()
        for site_key, entries in self._cred_entries.items():
            cred = svc.get_credential(site_key)
            entries["email"].delete(0, "end")
            entries["email"].insert(0, cred.email)
            entries["pass"].delete(0, "end")
            entries["pass"].insert(0, cred.password)

    def _save(self) -> None:
        settings = get_settings()
        settings.llm_api_key = self._api_key_entry.get().strip()
        settings.llm_model = self._model_entry.get().strip()
        settings.resume_path = self._resume_entry.get().strip()
        settings.profile_path = self._form_entry.get().strip()
        settings.db_path = self._db_entry.get().strip()
        settings.scheduler_interval = self._scheduler_var.get()
        settings.desktop_notifications_enabled = self._notif_var.get()
        settings.save()

        # Apply scheduler
        from services.scheduler_service import get_scheduler

        scheduler = get_scheduler()
        scheduler.apply_interval(settings.scheduler_interval)

        self._status_lbl.configure(
            text="[OK] Settings saved successfully!", text_color=COLORS["accent_green"]
        )
        self.after(3000, lambda: self._status_lbl.configure(text=""))

    # ── Credential + session helpers ───────────────────────────────────────────────────────────

    def _save_credentials(self) -> None:
        """Save site credentials to credentials.json for automatic login."""
        from services.auto_login_service import get_auto_login_service

        svc = get_auto_login_service()
        for site_key, entries in self._cred_entries.items():
            email = entries["email"].get().strip()
            pwd = entries["pass"].get().strip()
            svc.set_credential(site_key, email, pwd)
        svc.save()

        configured = [s for s in self._cred_entries if svc.has_credential(s)]
        self._status_lbl.configure(
            text=f"[OK] Credentials saved for: {', '.join(configured) or 'none'}. Auto-login is active.",
            text_color=COLORS["accent_green"],
        )
        self.after(5000, lambda: self._status_lbl.configure(text=""))

    def _reset_browser_profile(self) -> None:
        """Delete saved browser cookies and reset profile (requires re-login to all sites)."""
        from gui.widgets.dialogs import ConfirmationDialog

        def on_confirm():
            from automation.browser_manager import get_browser_manager

            get_browser_manager().clear_sessions()
            self._status_lbl.configure(
                text="[OK] Browser profile reset successfully. Re-login is required for all sites.",
                text_color=COLORS["accent_orange"],
            )
            self.after(5000, lambda: self._status_lbl.configure(text=""))

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
