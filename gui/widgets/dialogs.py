"""
Dialog widgets:
- ApplicationConfirmDialog  — shown before submitting an application
- CaptchaDialog             — shown when CAPTCHA is detected
- OTPDialog                 — shown when OTP is required
- LoginDialog               — shown when login is required
- MessageDialog             — generic info/error dialog
"""

from __future__ import annotations

import json
from collections.abc import Callable

import customtkinter as ctk

from config.constants import COLORS, FONTS
from core.models import Job


class _BaseDialog(ctk.CTkToplevel):
    """Base class for all application dialogs."""

    def __init__(self, parent, title: str, width: int = 460, height: int = 320):
        super().__init__(parent)
        self.title(title)
        self.geometry(f"{width}x{height}")
        self.resizable(False, False)
        self.configure(fg_color=COLORS["bg_primary"])
        self.grab_set()
        self.lift()
        self.focus_force()

        # Centre on parent
        self.update_idletasks()
        px = parent.winfo_rootx() + parent.winfo_width() // 2 - width // 2
        py = parent.winfo_rooty() + parent.winfo_height() // 2 - height // 2
        self.geometry(f"{width}x{height}+{px}+{py}")

    def _header(self, icon: str, title: str, subtitle: str = "") -> None:
        ctk.CTkLabel(
            self,
            text=icon,
            font=("Segoe UI Emoji", 36),
        ).pack(pady=(24, 4))
        ctk.CTkLabel(
            self,
            text=title,
            font=FONTS["heading_md"],
            text_color=COLORS["text_primary"],
        ).pack()
        if subtitle:
            ctk.CTkLabel(
                self,
                text=subtitle,
                font=FONTS["body_sm"],
                text_color=COLORS["text_secondary"],
                wraplength=400,
            ).pack(pady=(4, 0))


class ApplicationConfirmDialog(_BaseDialog):
    """
    Confirmation dialog shown before submitting a job application.
    Requires explicit user approval.
    """

    def __init__(self, parent, job: Job, on_confirm: Callable, on_cancel: Callable):
        super().__init__(parent, "Confirm Application", width=500, height=380)
        self._on_confirm = on_confirm
        self._on_cancel = on_cancel
        self._build(job)

    def _build(self, job: Job) -> None:
        self._header("📋", "Confirm Job Application")

        # Details card
        card = ctk.CTkFrame(
            self,
            fg_color=COLORS["bg_card"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
        )
        card.pack(padx=24, pady=16, fill="x")

        fields = [
            ("Company", job.company or "—"),
            ("Job Title", job.title or "—"),
            ("Source", job.source or "—"),
            ("URL", (job.url[:55] + "…") if len(job.url) > 55 else job.url),
        ]
        for i, (label, value) in enumerate(fields):
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=(8 if i == 0 else 2, 2))
            ctk.CTkLabel(
                row,
                text=label + ":",
                font=FONTS["label"],
                text_color=COLORS["text_secondary"],
                width=80,
                anchor="w",
            ).pack(side="left")
            ctk.CTkLabel(
                row,
                text=value,
                font=FONTS["body_md"],
                text_color=COLORS["text_primary"],
                anchor="w",
            ).pack(side="left", padx=(8, 0))

        # Warning
        ctk.CTkLabel(
            self,
            text="⚠️  The application will be submitted after form filling.",
            font=FONTS["body_sm"],
            text_color=COLORS["accent_orange"],
        ).pack(pady=(0, 8))

        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=8)

        ctk.CTkButton(
            btn_frame,
            text="✅  Proceed",
            fg_color=COLORS["accent_green"],
            hover_color="#16A34A",
            font=FONTS["body_md"],
            width=140,
            height=38,
            corner_radius=10,
            command=self._confirm,
        ).pack(side="left", padx=8)

        ctk.CTkButton(
            btn_frame,
            text="❌  Cancel",
            fg_color=COLORS["bg_hover"],
            hover_color=COLORS["accent_red"],
            font=FONTS["body_md"],
            width=140,
            height=38,
            corner_radius=10,
            command=self._cancel,
        ).pack(side="left", padx=8)

    def _confirm(self) -> None:
        self.destroy()
        self._on_confirm()

    def _cancel(self) -> None:
        self.destroy()
        self._on_cancel()


class CaptchaDialog(_BaseDialog):
    """
    Shown when CAPTCHA / human verification is detected.
    User clicks Resume after completing verification.
    """

    def __init__(self, parent, url: str, on_resume: Callable):
        super().__init__(parent, "Human Verification Required", width=480, height=300)
        self._on_resume = on_resume
        self._build(url)

    def _build(self, url: str) -> None:
        self._header(
            "⚠️",
            "Human Verification Required",
            "CAPTCHA or verification detected. Please complete it in the browser, then click Resume.",
        )

        url_lbl = ctk.CTkLabel(
            self,
            text=url[:70] if url else "Unknown URL",
            font=FONTS["mono"],
            text_color=COLORS["text_muted"],
        )
        url_lbl.pack(pady=(8, 16))

        ctk.CTkButton(
            self,
            text="▶  Resume Automation",
            fg_color=COLORS["accent_primary"],
            hover_color=COLORS["accent_secondary"],
            font=FONTS["body_md"],
            width=200,
            height=40,
            corner_radius=10,
            command=self._resume,
        ).pack()

    def _resume(self) -> None:
        self.destroy()
        self._on_resume()


class OTPDialog(_BaseDialog):
    """Shown when OTP is required."""

    def __init__(self, parent, on_submit: Callable[[str], None]):
        super().__init__(parent, "OTP Required", width=400, height=260)
        self._on_submit = on_submit
        self._build()

    def _build(self) -> None:
        self._header(
            "🔐", "OTP Verification Required", "Enter the OTP sent to your phone/email:"
        )

        self._otp_var = ctk.StringVar()
        entry = ctk.CTkEntry(
            self,
            textvariable=self._otp_var,
            font=FONTS["heading_md"],
            width=200,
            height=44,
            corner_radius=10,
            border_color=COLORS["accent_primary"],
            justify="center",
        )
        entry.pack(pady=16)
        entry.focus()

        ctk.CTkButton(
            self,
            text="Submit OTP",
            fg_color=COLORS["accent_primary"],
            hover_color=COLORS["accent_secondary"],
            font=FONTS["body_md"],
            width=160,
            height=38,
            corner_radius=10,
            command=self._submit,
        ).pack()

    def _submit(self) -> None:
        otp = self._otp_var.get().strip()
        if otp:
            self.destroy()
            self._on_submit(otp)


class LoginDialog(_BaseDialog):
    """Shown when login is required before automation can proceed."""

    def __init__(self, parent, source: str, on_done: Callable):
        super().__init__(parent, "Login Required", width=440, height=260)
        self._on_done = on_done
        self._build(source)

    def _build(self, source: str) -> None:
        self._header(
            "🔑",
            f"Login Required — {source}",
            f"Please sign in to {source} in the browser window, then click Done.",
        )
        ctk.CTkButton(
            self,
            text="✅  Done — I've logged in",
            fg_color=COLORS["accent_green"],
            hover_color="#16A34A",
            font=FONTS["body_md"],
            width=200,
            height=40,
            corner_radius=10,
            command=self._done,
        ).pack(pady=24)

    def _done(self) -> None:
        self.destroy()
        self._on_done()


class ConfirmationDialog(_BaseDialog):
    """
    Generic two-button confirmation dialog.
    Calls on_confirm() if user clicks Confirm, on_cancel() if they click Cancel.
    """

    def __init__(
        self,
        parent,
        title: str = "Confirm",
        message: str = "Are you sure?",
        on_confirm: Callable | None = None,
        on_cancel: Callable | None = None,
        confirm_text: str = "✅  Confirm",
        cancel_text: str = "❌  Cancel",
    ):
        super().__init__(parent, title, width=480, height=260)
        self._on_confirm = on_confirm
        self._on_cancel = on_cancel
        self._build(message, confirm_text, cancel_text)

    def _build(self, message: str, confirm_text: str, cancel_text: str) -> None:
        self._header("⚠️", self.title(), message)

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=16)

        ctk.CTkButton(
            btn_frame,
            text=confirm_text,
            fg_color=COLORS["accent_red"],
            hover_color="#B91C1C",
            font=FONTS["body_md"],
            width=160,
            height=38,
            corner_radius=10,
            command=self._confirm,
        ).pack(side="left", padx=8)

        ctk.CTkButton(
            btn_frame,
            text=cancel_text,
            fg_color=COLORS["bg_hover"],
            hover_color=COLORS["accent_primary"],
            font=FONTS["body_md"],
            width=160,
            height=38,
            corner_radius=10,
            command=self._cancel,
        ).pack(side="left", padx=8)

    def _confirm(self) -> None:
        self.destroy()
        if self._on_confirm:
            self._on_confirm()

    def _cancel(self) -> None:
        self.destroy()
        if self._on_cancel:
            self._on_cancel()


class MessageDialog(_BaseDialog):
    """Generic info/error/success message dialog."""

    def __init__(
        self,
        parent,
        title: str,
        message: str,
        icon: str = "ℹ️",
        button_text: str = "OK",
        on_close: Callable | None = None,
    ):
        super().__init__(parent, title, width=420, height=220)
        self._on_close = on_close
        self._build(icon, title, message, button_text)

    def _build(self, icon: str, title: str, message: str, btn: str) -> None:
        self._header(icon, title, message)
        ctk.CTkButton(
            self,
            text=btn,
            fg_color=COLORS["accent_primary"],
            hover_color=COLORS["accent_secondary"],
            font=FONTS["body_md"],
            width=120,
            height=36,
            corner_radius=10,
            command=self._close,
        ).pack(pady=16)

    def _close(self) -> None:
        self.destroy()
        if self._on_close:
            self._on_close()


class ImportLinksDialog(_BaseDialog):
    """Dialog to import job application URLs from multiple sources."""

    def __init__(self, parent):
        super().__init__(parent, "Import Job Links", width=550, height=450)
        self._build()

    def _build(self) -> None:
        self._header(
            "📥",
            "Import Job Links",
            "Paste URLs or import from file (TXT, CSV, JSON, Excel)",
        )

        # Tabview
        self._tabs = ctk.CTkTabview(self, width=500, height=260)
        self._tabs.pack(padx=24, pady=10, fill="both", expand=True)

        self._tab_paste = self._tabs.add("Paste Links")
        self._tab_file = self._tabs.add("Import File")

        # Paste Links Tab Layout
        self._text_area = ctk.CTkTextbox(
            self._tab_paste,
            font=FONTS["mono"],
            fg_color=COLORS["bg_secondary"],
            text_color=COLORS["text_primary"],
            wrap="none",
        )
        self._text_area.pack(fill="both", expand=True, padx=8, pady=8)
        self._text_area.insert("1.0", "https://")

        # File Import Tab Layout
        file_frame = ctk.CTkFrame(self._tab_file, fg_color="transparent")
        file_frame.pack(pady=40)

        self._file_path_var = ctk.StringVar(value="No file selected")
        ctk.CTkLabel(
            file_frame,
            textvariable=self._file_path_var,
            font=FONTS["body_md"],
            wraplength=400,
        ).pack(pady=10)

        ctk.CTkButton(
            file_frame,
            text="📁  Choose File...",
            command=self._choose_file,
            fg_color=COLORS["accent_primary"],
            hover_color=COLORS["accent_secondary"],
            font=FONTS["body_md"],
            width=180,
            height=36,
            corner_radius=8,
        ).pack()

        # Action Buttons Frame
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=12)

        ctk.CTkButton(
            btn_frame,
            text="⚡  Import and Queue",
            fg_color=COLORS["accent_green"],
            hover_color="#16A34A",
            font=FONTS["body_md"],
            width=180,
            height=38,
            corner_radius=10,
            command=self._process_import,
        ).pack(side="left", padx=8)

        ctk.CTkButton(
            btn_frame,
            text="❌  Close",
            fg_color=COLORS["bg_hover"],
            hover_color=COLORS["accent_red"],
            font=FONTS["body_md"],
            width=120,
            height=38,
            corner_radius=10,
            command=self.destroy,
        ).pack(side="left", padx=8)

    def _choose_file(self) -> None:
        from tkinter import filedialog

        filetypes = [
            ("All supported files", "*.txt;*.csv;*.json;*.xlsx;*.xls"),
            ("Text files", "*.txt"),
            ("CSV files", "*.csv"),
            ("JSON files", "*.json"),
            ("Excel spreadsheets", "*.xlsx;*.xls"),
        ]
        path = filedialog.askopenfilename(
            title="Select Links File", filetypes=filetypes
        )
        if path:
            self._file_path_var.set(path)

    def _process_import(self) -> None:
        urls = []
        active_tab = self._tabs.get()

        if active_tab == "Paste Links":
            content = self._text_area.get("1.0", "end")
            lines = content.splitlines()
            for line in lines:
                line = line.strip()
                if line.startswith(("http://", "https://")):
                    urls.append(line)
        else:
            path = self._file_path_var.get()
            if path and path != "No file selected":
                import os

                ext = os.path.splitext(path)[1].lower()
                try:
                    if ext == ".txt":
                        with open(path, "r", encoding="utf-8", errors="replace") as f:
                            for line in f:
                                line = line.strip()
                                if line.startswith(("http://", "https://")):
                                    urls.append(line)
                    elif ext == ".csv":
                        import csv

                        with open(path, "r", encoding="utf-8", errors="replace") as f:
                            reader = csv.reader(f)
                            for row in reader:
                                for cell in row:
                                    cell = cell.strip()
                                    if cell.startswith(("http://", "https://")):
                                        urls.append(cell)
                    elif ext == ".json":
                        with open(path, "r", encoding="utf-8", errors="replace") as f:
                            data = json.load(f)

                            def find_urls(obj):
                                if isinstance(obj, str):
                                    if obj.startswith(("http://", "https://")):
                                        urls.append(obj)
                                elif isinstance(obj, list):
                                    for item in obj:
                                        find_urls(item)
                                elif isinstance(obj, dict):
                                    for v in obj.values():
                                        find_urls(v)

                            find_urls(data)
                    elif ext in (".xlsx", ".xls"):
                        try:
                            import openpyxl

                            wb = openpyxl.load_workbook(path, read_only=True)
                            for sheet in wb.worksheets:
                                for row in sheet.iter_rows(values_only=True):
                                    for val in row:
                                        if isinstance(val, str) and (
                                            val.startswith(("http://", "https://"))
                                        ):
                                            urls.append(val)
                        except ImportError:
                            import re

                            with open(path, "rb") as f:
                                content = f.read().decode("utf-8", errors="ignore")
                                found = re.findall(r"https?://[^\s\"'<>]+", content)
                                urls.extend(found)
                except Exception as e:
                    from core.logger import get_logger

                    get_logger("ImportLinksDialog").error("Import file failed: %s", e)

        if not urls:
            from gui.widgets.dialogs import MessageDialog

            MessageDialog(
                self.master,
                "Import Failed",
                "No valid job application URLs were found. Please verify the file/links.",
                icon="❌",
            )
            return

        from core.models import Job, JobStatus
        from services.queue_manager import get_job_queue_manager

        jobs = []
        for url in urls:
            from urllib.parse import urlparse

            parsed = urlparse(url)
            domain = parsed.netloc.replace("www.", "").split(".")[0].capitalize()
            jobs.append(
                Job(
                    title="Generic Job Apply Link",
                    company=domain or "Direct Web Apply",
                    url=url,
                    source=domain.lower(),
                    status=JobStatus.NEW,
                )
            )

        async def do_enqueue():
            qm = get_job_queue_manager()
            await qm.enqueue_jobs(jobs)

        self.master.run_async(do_enqueue())

        self.destroy()
        from gui.widgets.dialogs import MessageDialog

        MessageDialog(
            self.master,
            "Import Success",
            f"Successfully imported and queued {len(urls)} job URLs!",
            icon="✅",
        )
