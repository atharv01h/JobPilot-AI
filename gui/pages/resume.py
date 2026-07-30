"""
Resume Page — view and configure active candidate resume PDF.
"""

from __future__ import annotations

from core.logger import get_logger

logger = get_logger(__name__)

import tkinter.filedialog as fd
from typing import TYPE_CHECKING

import customtkinter as ctk

from config.constants import COLORS, FONTS

if TYPE_CHECKING:
    from gui.app import App


class ResumePage(ctk.CTkFrame):
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
            text="Resume Settings",
            font=FONTS["heading_xl"],
            text_color=COLORS["text_primary"],
            anchor="w",
        ).grid(row=0, column=0, padx=32, pady=(28, 4), sticky="w")

        ctk.CTkLabel(
            self,
            text="Manage candidate resume PDF uploads",
            font=FONTS["body_md"],
            text_color=COLORS["text_muted"],
            anchor="w",
        ).grid(row=1, column=0, padx=32, pady=(0, 20), sticky="w")

        # Two-column layout
        columns = ctk.CTkFrame(self, fg_color="transparent")
        columns.grid(row=2, column=0, padx=32, pady=(0, 28), sticky="nsew")
        self.grid_rowconfigure(2, weight=1)
        columns.grid_columnconfigure((0, 1), weight=1)
        columns.grid_rowconfigure(0, weight=1)

        # Left Column: Active Resume PDF Status
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
            text="📄  Candidate Resume File",
            font=FONTS["heading_md"],
            text_color=COLORS["text_primary"],
            anchor="w",
        ).grid(row=0, column=0, padx=20, pady=(20, 8), sticky="w")

        self._resume_status = ctk.CTkLabel(
            resume_card,
            text="Verifying...",
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

        # Change Button
        ctk.CTkButton(
            resume_card,
            text="📂  Upload new PDF",
            font=FONTS["body_md"],
            fg_color=COLORS["accent_primary"],
            hover_color=COLORS["accent_secondary"],
            height=38,
            corner_radius=10,
            command=self._change_resume,
        ).grid(row=3, column=0, padx=20, pady=(16, 20), sticky="w")

        # Right Column: Resume PDF Extraction details
        details_card = ctk.CTkFrame(
            columns,
            fg_color=COLORS["bg_card"],
            corner_radius=16,
            border_width=1,
            border_color=COLORS["border"],
        )
        details_card.grid(row=0, column=1, padx=(8, 0), sticky="nsew")
        details_card.grid_columnconfigure(0, weight=1)
        details_card.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            details_card,
            text="📝  Parsed Text Preview",
            font=FONTS["heading_md"],
            text_color=COLORS["text_primary"],
            anchor="w",
        ).grid(row=0, column=0, padx=20, pady=(20, 8), sticky="w")

        self._extracted_text = ctk.CTkTextbox(
            details_card,
            font=FONTS["mono"],
            fg_color=COLORS["bg_secondary"],
            text_color=COLORS["text_primary"],
            border_color=COLORS["border"],
            border_width=1,
            corner_radius=10,
            state="disabled",
        )
        self._extracted_text.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="nsew")

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

        # Extracted Preview
        content = "No text extracted from active resume."
        if rs.exists:
            try:
                # Basic preview of text
                from services.resume_intelligence import get_resume_intelligence

                ri = get_resume_intelligence()
                if ri.is_ready():
                    profile = ri.get_profile()
                    if profile:
                        content = profile.to_context_string()[:2000] + "\n\n... [Truncated for preview] ..."
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)
        self._extracted_text.configure(state="normal")
        self._extracted_text.delete("1.0", "end")
        self._extracted_text.insert("1.0", content)
        self._extracted_text.configure(state="disabled")

    def on_show(self) -> None:
        self._refresh_resume()
