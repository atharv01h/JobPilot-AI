"""
Onboarding wizard for first-time users to set up their resume and profile.
"""

from __future__ import annotations

from core.logger import get_logger

logger = get_logger(__name__)

import customtkinter as ctk

from config.constants import COLORS, FONTS


class OnboardingWizard(ctk.CTkToplevel):
    def __init__(self, master, on_complete: callable):
        super().__init__(master)
        self.title("Welcome to JobPilot AI")
        self.geometry("600x500")
        self.resizable(False, False)
        self.configure(fg_color=COLORS["bg_primary"])
        self.transient(master)
        self.grab_set()

        # Center the window
        self.update_idletasks()
        try:
            x = master.winfo_x() + (master.winfo_width() - 600) // 2
            y = master.winfo_y() + (master.winfo_height() - 500) // 2
            self.geometry(f"+{x}+{y}")
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)

        self.on_complete = on_complete

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # Title
        ctk.CTkLabel(
            self,
            text="Welcome to JobPilot AI! 🚀",
            font=FONTS["heading_xl"],
            text_color=COLORS["text_primary"],
        ).grid(row=0, column=0, pady=(40, 10))

        ctk.CTkLabel(
            self,
            text="Before the AI can start applying to jobs for you, please complete your profile and upload your resume.",
            font=FONTS["body_lg"],
            text_color=COLORS["text_muted"],
            wraplength=480,
            justify="center",
        ).grid(row=1, column=0, padx=40, pady=(0, 30))

        # Main content area
        frame = ctk.CTkFrame(self, fg_color=COLORS["bg_card"], corner_radius=16)
        frame.grid(row=2, column=0, padx=40, pady=(0, 40), sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)

        # Step 1: Profile
        self.profile_btn = ctk.CTkButton(
            frame,
            text="📝 Step 1: Fill Basic Profile",
            font=FONTS["heading_md"],
            fg_color=COLORS["accent_primary"],
            hover_color=COLORS["accent_secondary"],
            height=50,
            corner_radius=12,
            command=self._go_to_profile,
        )
        self.profile_btn.grid(row=0, column=0, padx=40, pady=(40, 20), sticky="ew")

        # Step 2: Resume
        self.resume_btn = ctk.CTkButton(
            frame,
            text="📄 Step 2: Upload Resume PDF",
            font=FONTS["heading_md"],
            fg_color=COLORS["accent_primary"],
            hover_color=COLORS["accent_secondary"],
            height=50,
            corner_radius=12,
            command=self._go_to_resume,
        )
        self.resume_btn.grid(row=1, column=0, padx=40, pady=20, sticky="ew")

    def _go_to_profile(self) -> None:
        self.destroy()
        self.on_complete("profile")

    def _go_to_resume(self) -> None:
        self.destroy()
        self.on_complete("resume")

    def _on_close(self) -> None:
        self.destroy()
        self.on_complete(None)
