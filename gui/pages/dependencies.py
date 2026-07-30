"""
Dependencies Page — lists status of all required/optional python libraries.
Allows user to trigger manual package installation and identifies file lock conflicts.
"""

from __future__ import annotations

from core.logger import get_logger

logger = get_logger(__name__)

import threading
from typing import TYPE_CHECKING

import customtkinter as ctk

from automation.dependency_guard import (
    _PACKAGES,
    check_dependencies,
    ensure_all,
    find_locking_processes,
)
from automation.dependency_installer import DependencyInstaller
from config.constants import COLORS, FONTS

if TYPE_CHECKING:
    from gui.app import App


class DependenciesPage(ctk.CTkFrame):
    def __init__(self, master, app: App, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_primary"], **kwargs)
        self._app = app
        self._after_ids: set[str] = set()
        self._is_installing = False
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

        # ── Header ───────────────────────────────────────────────────────────
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=32, pady=(24, 0), sticky="ew")

        ctk.CTkLabel(
            header,
            text="Dependencies Manager",
            font=FONTS["heading_xl"],
            text_color=COLORS["text_primary"],
        ).pack(side="left")

        # ── Controls ─────────────────────────────────────────────────────────
        ctrl_bar = ctk.CTkFrame(
            self,
            fg_color=COLORS["bg_card"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
        )
        ctrl_bar.grid(row=1, column=0, padx=32, pady=12, sticky="ew")

        self._btn_install = ctk.CTkButton(
            ctrl_bar,
            text="🔧 Install Missing Packages",
            font=FONTS["body_sm"],
            height=32,
            fg_color=COLORS["accent_primary"],
            hover_color=COLORS["bg_hover"],
            command=self._start_install,
        )
        self._btn_install.pack(side="left", padx=12, pady=8)

        self._btn_refresh = ctk.CTkButton(
            ctrl_bar,
            text="🔄 Check Status",
            font=FONTS["body_sm"],
            height=32,
            fg_color=COLORS["bg_hover"],
            text_color=COLORS["text_primary"],
            command=self.refresh,
        )
        self._btn_refresh.pack(side="left", padx=4, pady=8)

        self._status_lbl = ctk.CTkLabel(
            ctrl_bar,
            text="All dependencies checked.",
            font=FONTS["body_sm"],
            text_color=COLORS["text_muted"],
        )
        self._status_lbl.pack(side="right", padx=12)

        # ── Scrollable list & diagnostics ────────────────────────────────────
        content_frame = ctk.CTkFrame(self, fg_color="transparent")
        content_frame.grid(row=2, column=0, padx=32, pady=(0, 20), sticky="nsew")
        content_frame.grid_columnconfigure(0, weight=3)
        content_frame.grid_columnconfigure(1, weight=2)
        content_frame.grid_rowconfigure(0, weight=1)

        self._list_scroll = ctk.CTkScrollableFrame(
            content_frame,
            fg_color=COLORS["bg_secondary"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
        )
        self._list_scroll.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        # Diagnostics Panel
        self._diag_frame = ctk.CTkFrame(
            content_frame,
            fg_color=COLORS["bg_card"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
        )
        self._diag_frame.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self._diag_frame.grid_columnconfigure(0, weight=1)
        self._diag_frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            self._diag_frame,
            text="🔍 Installation Diagnostics",
            font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"],
        ).grid(row=0, column=0, padx=16, pady=(16, 8), sticky="w")

        self._diag_text = ctk.CTkTextbox(
            self._diag_frame,
            wrap="word",
            font=FONTS["mono"],
            fg_color=COLORS["bg_secondary"],
            border_width=1,
            border_color=COLORS["border"],
        )
        self._diag_text.grid(row=1, column=0, padx=16, pady=(0, 16), sticky="nsew")
        self._diag_text.insert(
            "0.0",
            "Diagnostics output will appear here if package installations fail or encounter file locks.",
        )
        self._diag_text.configure(state="disabled")

        self.refresh()

    def refresh(self) -> None:
        """Scan system libraries and update UI statuses."""
        if not self.winfo_exists():
            return

        for child in self._list_scroll.winfo_children():
            child.destroy()

        import importlib

        missing_count = 0

        # Header Row
        header_row = ctk.CTkFrame(self._list_scroll, fg_color="transparent", height=28)
        header_row.pack(fill="x", padx=8, pady=4)
        header_row.grid_columnconfigure(0, weight=2)
        header_row.grid_columnconfigure(1, weight=2)
        header_row.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(
            header_row,
            text="LIBRARY",
            font=FONTS["label"],
            text_color=COLORS["text_muted"],
        ).grid(row=0, column=0, sticky="w", padx=10)
        ctk.CTkLabel(
            header_row,
            text="PIP PACKAGE",
            font=FONTS["label"],
            text_color=COLORS["text_muted"],
        ).grid(row=0, column=1, sticky="w", padx=10)
        ctk.CTkLabel(
            header_row,
            text="STATUS",
            font=FONTS["label"],
            text_color=COLORS["text_muted"],
        ).grid(row=0, column=2, sticky="e", padx=10)

        for i, (import_name, pip_name, flag) in enumerate(_PACKAGES):
            row = ctk.CTkFrame(
                self._list_scroll,
                fg_color=COLORS["bg_card"] if i % 2 == 0 else COLORS["bg_secondary"],
                height=40,
                corner_radius=6,
            )
            row.pack(fill="x", padx=8, pady=2)
            row.grid_columnconfigure(0, weight=2)
            row.grid_columnconfigure(1, weight=2)
            row.grid_columnconfigure(2, weight=1)

            ctk.CTkLabel(
                row,
                text=import_name,
                font=FONTS["heading_sm"],
                text_color=COLORS["text_primary"],
            ).grid(row=0, column=0, sticky="w", padx=12, pady=6)
            ctk.CTkLabel(
                row,
                text=pip_name,
                font=FONTS["body_sm"],
                text_color=COLORS["text_secondary"],
            ).grid(row=0, column=1, sticky="w", padx=12, pady=6)

            # Check status
            try:
                importlib.import_module(import_name)
                status_text = "Available"
                status_color = COLORS["accent_green"]
            except ImportError:
                status_text = "Missing"
                status_color = COLORS["accent_red"]
                missing_count += 1

            lbl_status = ctk.CTkLabel(
                row,
                text=status_text,
                font=FONTS["heading_sm"],
                text_color="#FFFFFF",
                fg_color=status_color,
                corner_radius=6,
                width=90,
                height=22,
            )
            lbl_status.grid(row=0, column=2, sticky="e", padx=12, pady=6)

        if missing_count > 0:
            self._status_lbl.configure(
                text=f"Warning: {missing_count} package(s) missing.",
                text_color=COLORS["accent_red"],
            )
            self._btn_install.configure(
                state="normal", text="🔧 Install Missing Packages"
            )
        else:
            self._status_lbl.configure(
                text="All required dependencies are satisfied.",
                text_color=COLORS["accent_green"],
            )
            self._btn_install.configure(state="disabled", text="✓ All Installed")

    def _start_install(self) -> None:
        if self._is_installing:
            return
        self._is_installing = True
        self._btn_install.configure(state="disabled", text="🔧 Installing...")
        self._btn_refresh.configure(state="disabled")

        self._diag_text.configure(state="normal")
        self._diag_text.delete("0.0", "end")
        self._diag_text.insert("0.0", "Starting manual dependency installer...\n")
        self._diag_text.configure(state="disabled")

        threading.Thread(target=self._run_installer, daemon=True).start()

    def _run_installer(self) -> None:
        missing = check_dependencies()
        if not missing:
            self.after(0, self._install_finished)
            return

        installer = DependencyInstaller()
        for import_name, pip_name, flag in missing:
            self._log_diag(f"Installing {pip_name} via pip...\n")
            res = installer.install_package(pip_name, log_callback=self._log_diag)
            if not res:
                self._log_diag(f"❌ Failed to install {pip_name}!\n")

                # Run diagnostic check for lock conflicts (especially for cv2 / easyocr)
                self._log_diag(
                    "Checking for processes locking Python/OpenCV modules...\n"
                )
                locking = find_locking_processes("cv2")
                if not locking:
                    locking = find_locking_processes("easyocr")

                if locking:
                    procs_str = "\n".join([f" • {p}" for p in locking])
                    self._log_diag(
                        f"⚠️ FILE LOCK CONFLICT DETECTED!\n"
                        f"The following process(es) appear to be locking the package files:\n"
                        f"{procs_str}\n\n"
                        f"SOLUTION:\n"
                        f"Please close these programs or restart your IDE/editor, then try installing again.\n"
                    )
                else:
                    self._log_diag(
                        "No file locks detected. Check network permissions or try executing:\n"
                        f"pip install {pip_name}\n"
                        "manually in an administrator command prompt.\n"
                    )
            else:
                self._log_diag(f"✓ Installed {pip_name} successfully.\n")

        self.after(0, self._install_finished)

    def _install_finished(self) -> None:
        self._is_installing = False
        self._btn_refresh.configure(state="normal")
        ensure_all()  # refresh global disabled strategy flags
        self.refresh()

    def _log_diag(self, text: str) -> None:
        if not self.winfo_exists():
            return

        def _update():
            self._diag_text.configure(state="normal")
            self._diag_text.insert("end", text)
            self._diag_text.see("end")
            self._diag_text.configure(state="disabled")

        self.after(0, _update)

    def on_show(self) -> None:
        self.refresh()
