"""
Installer Screen — Automatic dependency setup wizard on first launch.
"""

from __future__ import annotations

import threading

import customtkinter as ctk

from automation.dependency_guard import check_dependencies
from automation.dependency_installer import DependencyInstaller
from config.constants import COLORS, FONTS


class InstallerScreen(ctk.CTkFrame):
    def __init__(
        self, master, missing_packages: list, on_complete: callable, **kwargs
    ) -> None:
        super().__init__(master, fg_color=COLORS["bg_primary"], **kwargs)
        self._missing_packages = missing_packages
        self._on_complete = on_complete
        self._installer = DependencyInstaller()
        self._is_installing = False
        self._build()

        # Start installation automatically after a brief delay
        self.after(1000, self._start_installation)

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=32, pady=(40, 20), sticky="ew")

        ctk.CTkLabel(
            header,
            text="First-Time Setup: Installing Dependencies",
            font=FONTS["heading_xl"],
            text_color=COLORS["text_primary"],
        ).pack(anchor="w")

        self.status_lbl = ctk.CTkLabel(
            header,
            text="Preparing to install...",
            font=FONTS["body_lg"],
            text_color=COLORS["text_secondary"],
        )
        self.status_lbl.pack(anchor="w", pady=(10, 0))

        # Progress
        self.progress_bar = ctk.CTkProgressBar(
            self, height=8, corner_radius=4, progress_color=COLORS["accent_primary"]
        )
        self.progress_bar.grid(row=1, column=0, padx=32, pady=10, sticky="ew")
        self.progress_bar.set(0)

        # Terminal Log
        self.log_textbox = ctk.CTkTextbox(
            self,
            font=FONTS["mono"],
            fg_color=COLORS["bg_secondary"],
            text_color=COLORS["text_primary"],
            wrap="word",
        )
        self.log_textbox.grid(row=2, column=0, padx=32, pady=(10, 32), sticky="nsew")
        self.log_textbox.insert(
            "end", "Welcome to JobPilot AI. Analyzing missing dependencies...\n"
        )
        self.log_textbox.configure(state="disabled")

        # Retry Button (hidden initially)
        self.retry_btn = ctk.CTkButton(
            self,
            text="Retry Installation",
            font=FONTS["heading_sm"],
            fg_color=COLORS["accent_red"],
            hover_color=COLORS["bg_hover"],
            command=self._start_installation,
        )

    def _log(self, msg: str) -> None:
        if not self.winfo_exists():
            return

        def _update():
            self.log_textbox.configure(state="normal")
            self.log_textbox.insert("end", msg)
            self.log_textbox.see("end")
            self.log_textbox.configure(state="disabled")

        self.after(0, _update)

    def _update_status(self, text: str, progress: float) -> None:
        if not self.winfo_exists():
            return

        def _update():
            self.status_lbl.configure(text=text, text_color=COLORS["text_secondary"])
            self.progress_bar.configure(progress_color=COLORS["accent_primary"])
            self.progress_bar.set(progress)

        self.after(0, _update)

    def _start_installation(self) -> None:
        if self._is_installing:
            return
        self._is_installing = True
        self.retry_btn.grid_forget()
        self._update_status("Upgrading core tools...", 0.05)

        threading.Thread(target=self._run_installation_thread, daemon=True).start()

    def _run_installation_thread(self) -> None:
        try:
            # 1. Upgrade pip/setuptools/wheel
            self._installer.upgrade_core(log_callback=self._log)

            # 2. Re-evaluate missing packages (in case something changed)
            missing = check_dependencies()
            total = len(missing)

            if total == 0:
                self._update_status("All dependencies are already satisfied!", 1.0)
                self.after(1000, self._on_complete)
                return

            # 3. Install packages
            for idx, (import_name, pip_name, _) in enumerate(missing):
                progress = 0.1 + (idx / total) * 0.8
                self._update_status(
                    f"Installing {pip_name} ({idx+1}/{total})...", progress
                )

                success = self._installer.install_package(
                    pip_name, log_callback=self._log
                )
                if not success:
                    self._handle_failure(f"Failed to install {pip_name}")
                    return

                # Verify
                self._update_status(
                    f"Verifying {import_name}...", progress + (0.8 / total / 2)
                )
                if not self._installer.verify_import(import_name):
                    self._handle_failure(
                        f"Failed to verify import of {import_name} after installation."
                    )
                    return

            self._update_status("Installation complete!", 1.0)
            self._log("\n🎉 All dependencies installed and verified successfully.\n")
            self.after(1500, self._on_complete)

        except Exception as e:
            self._handle_failure(f"Unexpected error: {e}")

    def _handle_failure(self, reason: str) -> None:
        self._is_installing = False

        def _show_err():
            self.status_lbl.configure(
                text=f"Installation failed: {reason}", text_color=COLORS["accent_red"]
            )
            self.progress_bar.configure(progress_color=COLORS["accent_red"])
            self.retry_btn.grid(row=3, column=0, padx=32, pady=(0, 32), sticky="e")
            self._log(f"\n[FATAL] {reason}\nPlease check your network or permissions.\n")

        self.after(0, _show_err)
