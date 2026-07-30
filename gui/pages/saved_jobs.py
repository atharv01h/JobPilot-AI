"""Saved Jobs page."""

from __future__ import annotations

import webbrowser
from typing import TYPE_CHECKING

import customtkinter as ctk

from config.constants import COLORS, FONTS
from core.models import Job
from gui.widgets.job_detail_panel import JobDetailPanel
from gui.widgets.job_table import JobTable

if TYPE_CHECKING:
    from gui.app import App


class SavedJobsPage(ctk.CTkFrame):
    def __init__(self, master, app: App, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_primary"], **kwargs)
        self._app = app
        self._build()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=32, pady=(28, 0), sticky="ew")
        ctk.CTkLabel(
            header,
            text="Saved Jobs",
            font=FONTS["heading_xl"],
            text_color=COLORS["text_primary"],
        ).pack(side="left")

        ctk.CTkButton(
            header,
            text="↻  Refresh",
            fg_color=COLORS["bg_hover"],
            hover_color=COLORS["accent_primary"],
            font=FONTS["body_md"],
            height=38,
            corner_radius=10,
            command=self.on_show,
        ).pack(side="right")

        ctk.CTkLabel(
            self,
            text="Jobs you've bookmarked for later review",
            font=FONTS["body_md"],
            text_color=COLORS["text_muted"],
            anchor="w",
        ).grid(row=1, column=0, padx=32, pady=(4, 16), sticky="w")

        # Content
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.grid(row=2, column=0, padx=32, pady=(0, 28), sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_columnconfigure(1, weight=0)
        content.grid_rowconfigure(0, weight=1)

        def _open_url(j: Job) -> None:
            if j.url:
                webbrowser.open(j.url)

        self._table = JobTable(
            content,
            on_select=lambda j: self._detail.show_job(j),
            on_open=_open_url,
            on_save=None,
            on_apply=self._apply_saved,
        )
        self._table.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        self._detail = JobDetailPanel(content, width=360)
        self._detail.grid(row=0, column=1, sticky="nsew")

    def _apply_saved(self, job: Job) -> None:
        if not job.id:
            return
        from gui.widgets.dialogs import ApplicationConfirmDialog

        def on_confirm():
            async def _do():
                from automation.form_filler import FormFiller

                filler = FormFiller()
                success = await filler.assist_application(job)
                if success:
                    from services.job_service import get_job_service

                    await get_job_service().mark_applied(job.id, job.url)
                self.after(0, self.on_show)

            self._app.run_async(_do())

        ApplicationConfirmDialog(
            self._app, job, on_confirm=on_confirm, on_cancel=lambda: None
        )

    def on_show(self) -> None:
        async def _load():
            from services.job_service import get_job_service

            saved = await get_job_service().get_saved_jobs()
            jobs = [s.job for s in saved if s.job]
            self.after(0, lambda: self._table.load_jobs(jobs))

        self._app.run_async(_load())
