"""
Resume Manager page.
Shows current resume path, status, and parsed form.txt contents.
"""

from __future__ import annotations

import tkinter.filedialog as fd
from typing import TYPE_CHECKING

import customtkinter as ctk

from config.constants import COLORS, FONTS

if TYPE_CHECKING:
    from gui.app import App


class ResumeManagerPage(ctk.CTkFrame):
    def __init__(self, master, app: App, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_primary"], **kwargs)
        self._app = app
        self._build()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        # Header
        ctk.CTkLabel(
            self,
            text="Resume Manager",
            font=FONTS["heading_xl"],
            text_color=COLORS["text_primary"],
            anchor="w",
        ).grid(row=0, column=0, padx=32, pady=(28, 4), sticky="w")
        ctk.CTkLabel(
            self,
            text="Manage your resume and application profile",
            font=FONTS["body_md"],
            text_color=COLORS["text_muted"],
            anchor="w",
        ).grid(row=1, column=0, padx=32, pady=(0, 20), sticky="w")

        # ── Two-column layout ─────────────────────────────────────────────────
        columns = ctk.CTkFrame(self, fg_color="transparent")
        columns.grid(row=2, column=0, padx=32, pady=(0, 28), sticky="nsew")
        self.grid_rowconfigure(2, weight=1)
        columns.grid_columnconfigure((0, 1), weight=1)
        columns.grid_rowconfigure(0, weight=1)

        # ── Left: Resume card ─────────────────────────────────────────────────
        resume_card = ctk.CTkFrame(
            columns,
            fg_color=COLORS["bg_card"],
            corner_radius=16,
            border_width=1,
            border_color=COLORS["border"],
        )
        resume_card.grid(row=0, column=0, padx=(0, 8), sticky="nsew")
        resume_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            resume_card,
            text="📄  Resume",
            font=FONTS["heading_md"],
            text_color=COLORS["text_primary"],
            anchor="w",
        ).grid(row=0, column=0, padx=20, pady=(20, 8), sticky="w")

        self._resume_status = ctk.CTkLabel(
            resume_card,
            text="Loading…",
            font=FONTS["body_lg"],
            text_color=COLORS["accent_green"],
            anchor="w",
            wraplength=350,
        )
        self._resume_status.grid(row=1, column=0, padx=20, pady=4, sticky="w")

        self._resume_path_lbl = ctk.CTkLabel(
            resume_card,
            text="",
            font=FONTS["mono"],
            text_color=COLORS["text_muted"],
            anchor="w",
            wraplength=350,
        )
        self._resume_path_lbl.grid(row=2, column=0, padx=20, pady=4, sticky="w")

        # Change button
        ctk.CTkButton(
            resume_card,
            text="📂  Change Resume",
            font=FONTS["body_md"],
            fg_color=COLORS["accent_primary"],
            hover_color=COLORS["accent_secondary"],
            height=38,
            corner_radius=10,
            command=self._change_resume,
        ).grid(row=3, column=0, padx=20, pady=(16, 20), sticky="w")

        # ── Right: Form data viewer ───────────────────────────────────────────
        form_card = ctk.CTkFrame(
            columns,
            fg_color=COLORS["bg_card"],
            corner_radius=16,
            border_width=1,
            border_color=COLORS["border"],
        )
        form_card.grid(row=0, column=1, padx=(8, 0), sticky="nsew")
        form_card.grid_columnconfigure(0, weight=1)
        form_card.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            form_card,
            text="📋  Application Profile (form.txt)",
            font=FONTS["heading_md"],
            text_color=COLORS["text_primary"],
            anchor="w",
        ).grid(row=0, column=0, padx=20, pady=(20, 8), sticky="w")

        self._form_text = ctk.CTkTextbox(
            form_card,
            font=FONTS["mono"],
            fg_color=COLORS["bg_secondary"],
            text_color=COLORS["text_primary"],
            border_color=COLORS["border"],
            border_width=1,
            corner_radius=10,
            state="disabled",
        )
        self._form_text.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="nsew")

    def _change_resume(self) -> None:
        path = fd.askopenfilename(
            title="Select Resume PDF",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if path:
            from config.settings import get_settings
            from services.resume_service import get_resume_service

            rs = get_resume_service()
            if rs.set_path(path):
                settings = get_settings()
                settings.resume_path = path
                settings.save()
                self._refresh_resume()

    def _refresh_resume(self) -> None:
        from services.resume_service import get_resume_service

        rs = get_resume_service()
        status = rs.get_status_text()
        self._resume_status.configure(
            text=status,
            text_color=COLORS["accent_green"] if rs.exists else COLORS["accent_red"],
        )
        self._resume_path_lbl.configure(text=rs.path_str)

    def _refresh_form(self) -> None:
        from services.form_service import get_form_service

        fs = get_form_service()
        if fs.is_loaded:
            content = fs.raw
        else:
            content = "profile.json not found or failed to load.\n\nExpected path:\n" + str(
                fs.profile_path
            )
        self._form_text.configure(state="normal")
        self._form_text.delete("1.0", "end")
        self._form_text.insert("1.0", content)
        self._form_text.configure(state="disabled")

    def on_show(self) -> None:
        self._refresh_resume()
        self._refresh_form()
