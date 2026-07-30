"""Applied Jobs page."""

from __future__ import annotations

import webbrowser
from tkinter import ttk
from typing import TYPE_CHECKING

import customtkinter as ctk

from config.constants import COLORS, FONTS
from core.models import AppliedJob

if TYPE_CHECKING:
    from gui.app import App


class AppliedJobsPage(ctk.CTkFrame):
    def __init__(self, master, app: App, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_primary"], **kwargs)
        self._app = app
        self._applied: list[AppliedJob] = []
        self._build()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=32, pady=(28, 0), sticky="ew")
        ctk.CTkLabel(
            header,
            text="Applied Jobs",
            font=FONTS["heading_xl"],
            text_color=COLORS["text_primary"],
        ).pack(side="left")

        ctk.CTkButton(
            header,
            text="📥  Export CSV",
            fg_color=COLORS["bg_hover"],
            hover_color=COLORS["accent_cyan"],
            font=FONTS["body_md"],
            height=38,
            corner_radius=10,
            command=self._export,
        ).pack(side="right")

        ctk.CTkButton(
            header,
            text="↻  Refresh",
            fg_color=COLORS["bg_hover"],
            hover_color=COLORS["accent_primary"],
            font=FONTS["body_md"],
            height=38,
            corner_radius=10,
            command=self.on_show,
        ).pack(side="right", padx=(0, 10))

        ctk.CTkLabel(
            self,
            text="All jobs you have applied to",
            font=FONTS["body_md"],
            text_color=COLORS["text_muted"],
            anchor="w",
        ).grid(row=1, column=0, padx=32, pady=(4, 16), sticky="w")

        # Table
        table_frame = ctk.CTkFrame(
            self,
            fg_color=COLORS["bg_secondary"],
            corner_radius=12,
        )
        table_frame.grid(row=2, column=0, padx=32, pady=(0, 28), sticky="nsew")
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        # Style
        style = ttk.Style()
        style.configure(
            "Applied.Treeview",
            background=COLORS["bg_secondary"],
            foreground=COLORS["text_primary"],
            fieldbackground=COLORS["bg_secondary"],
            rowheight=38,
            font=("Inter", 11),
            borderwidth=0,
        )
        style.configure(
            "Applied.Treeview.Heading",
            background=COLORS["bg_card"],
            foreground=COLORS["text_secondary"],
            font=("Inter", 11, "bold"),
        )
        style.map(
            "Applied.Treeview",
            background=[("selected", COLORS["accent_green"])],
            foreground=[("selected", "#FFF")],
        )

        cols = ("title", "company", "location", "source", "applied_date", "status")
        self._tree = ttk.Treeview(
            table_frame,
            columns=cols,
            show="headings",
            style="Applied.Treeview",
            selectmode="browse",
        )
        headers = {
            "title": "Job Title",
            "company": "Company",
            "location": "Location",
            "source": "Source",
            "applied_date": "Applied On",
            "status": "Status",
        }
        widths = {
            "title": 240,
            "company": 150,
            "location": 120,
            "source": 90,
            "applied_date": 110,
            "status": 90,
        }
        for col in cols:
            self._tree.heading(col, text=headers[col])
            self._tree.column(col, width=widths[col])
        self._tree.grid(row=0, column=0, sticky="nsew")
        self._tree.bind("<Double-1>", self._open_url)

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.grid(row=0, column=1, sticky="ns")

        self._count_lbl = ctk.CTkLabel(
            self,
            text="",
            font=FONTS["body_sm"],
            text_color=COLORS["text_muted"],
        )
        self._count_lbl.grid(row=3, column=0, padx=32, pady=(0, 8), sticky="w")

    def _open_url(self, _event=None) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        iid = sel[0]
        for aj in self._applied:
            if str(aj.id) == iid:
                url = aj.application_url or (aj.job.url if aj.job else "")
                if url:
                    webbrowser.open(url)
                break

    def _export(self) -> None:
        async def _do():
            from services.job_service import get_job_service

            _, applied_f = await get_job_service().export_csv()
            self.after(
                0, lambda: self._count_lbl.configure(text=f"Exported to: {applied_f}")
            )

        self._app.run_async(_do())

    def on_show(self) -> None:
        async def _load():
            from services.job_service import get_job_service

            self._applied = await get_job_service().get_applied_jobs()
            self.after(0, self._populate)

        self._app.run_async(_load())

    def _populate(self) -> None:
        self._tree.delete(*self._tree.get_children())
        for aj in self._applied:
            j = aj.job
            self._tree.insert(
                "",
                "end",
                iid=str(aj.id),
                values=(
                    (j.title if j else "")[:50],
                    (j.company if j else "")[:30],
                    (j.location if j else "")[:25],
                    (j.source if j else ""),
                    aj.applied_date[:10],
                    aj.status.capitalize(),
                ),
            )
        self._count_lbl.configure(text=f"{len(self._applied)} applied jobs")
