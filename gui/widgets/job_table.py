"""
Job table widget — a scrollable table for displaying Job lists.
Built with ttk.Treeview styled for the dark theme.
"""

from __future__ import annotations

from collections.abc import Callable
from tkinter import ttk

import customtkinter as ctk

from config.constants import COLORS, FONTS
from core.models import Job


class JobTable(ctk.CTkFrame):
    """
    A themed, scrollable table for displaying Job objects.
    Supports row selection callbacks and action buttons per row.
    """

    COLUMNS = ("title", "company", "location", "source", "date", "status")
    COL_HEADERS = {
        "title": "Job Title",
        "company": "Company",
        "location": "Location",
        "source": "Source",
        "date": "Posted",
        "status": "Status",
    }
    COL_WIDTHS = {
        "title": 240,
        "company": 160,
        "location": 120,
        "source": 90,
        "date": 90,
        "status": 80,
    }

    STATUS_COLORS = {
        "new": COLORS["accent_primary"],
        "saved": COLORS["accent_cyan"],
        "applied": COLORS["accent_green"],
        "error": COLORS["accent_red"],
    }

    def __init__(
        self,
        master,
        on_select: Callable[[Job], None] | None = None,
        on_open: Callable[[Job], None] | None = None,
        on_save: Callable[[Job], None] | None = None,
        on_apply: Callable[[Job], None] | None = None,
        show_actions: bool = True,
        **kwargs,
    ):
        super().__init__(master, fg_color=COLORS["bg_secondary"], **kwargs)
        self._on_select = on_select
        self._on_open = on_open
        self._on_save = on_save
        self._on_apply = on_apply
        self._jobs: list[Job] = []
        self._selected_job: Job | None = None
        self._show_actions = show_actions

        self._style_treeview()
        self._build()

    def _style_treeview(self) -> None:
        style = ttk.Style()
        style.theme_use("default")

        bg = COLORS["bg_secondary"]
        card = COLORS["bg_card"]
        sel = COLORS["accent_primary"]
        fg = COLORS["text_primary"]
        head = COLORS["text_secondary"]

        style.configure(
            "JobTable.Treeview",
            background=bg,
            foreground=fg,
            fieldbackground=bg,
            rowheight=38,
            font=("Inter", 11),
            borderwidth=0,
        )
        style.configure(
            "JobTable.Treeview.Heading",
            background=card,
            foreground=head,
            font=("Inter", 11, "bold"),
            borderwidth=0,
            relief="flat",
        )
        style.map(
            "JobTable.Treeview",
            background=[("selected", sel)],
            foreground=[("selected", "#FFFFFF")],
        )
        style.layout(
            "JobTable.Treeview",
            [
                ("Treeview.treearea", {"sticky": "nswe"}),
            ],
        )

    def _build(self) -> None:
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Treeview
        self._tree = ttk.Treeview(
            self,
            columns=self.COLUMNS,
            show="headings",
            style="JobTable.Treeview",
            selectmode="browse",
        )

        for col in self.COLUMNS:
            self._tree.heading(col, text=self.COL_HEADERS[col])
            self._tree.column(col, width=self.COL_WIDTHS[col], minwidth=60)

        self._tree.grid(row=0, column=0, sticky="nsew")
        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self._tree.bind("<Double-1>", self._on_double_click)

        # Scrollbar
        vsb = ttk.Scrollbar(self, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.grid(row=0, column=1, sticky="ns")

        # Tag colours for status
        for status, color in self.STATUS_COLORS.items():
            self._tree.tag_configure(status, foreground=color)

        # Action buttons bar (optional)
        if self._show_actions:
            btn_frame = ctk.CTkFrame(self, fg_color=COLORS["bg_card"], height=52)
            btn_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(1, 0))
            btn_frame.grid_propagate(False)

            btn_cfg = {"height": 34, "corner_radius": 8, "font": FONTS["body_sm"]}

            self._btn_open = ctk.CTkButton(
                btn_frame,
                text="🔗  Open Job",
                fg_color=COLORS["bg_hover"],
                hover_color=COLORS["accent_primary"],
                **btn_cfg,
                command=self._action_open,
            )
            self._btn_open.pack(side="left", padx=10, pady=8)

            self._btn_save = ctk.CTkButton(
                btn_frame,
                text="🔖  Save Job",
                fg_color=COLORS["bg_hover"],
                hover_color=COLORS["accent_cyan"],
                **btn_cfg,
                command=self._action_save,
            )
            self._btn_save.pack(side="left", padx=4, pady=8)

            self._btn_apply = ctk.CTkButton(
                btn_frame,
                text="✅  Mark Applied",
                fg_color=COLORS["bg_hover"],
                hover_color=COLORS["accent_green"],
                **btn_cfg,
                command=self._action_apply,
            )
            self._btn_apply.pack(side="left", padx=4, pady=8)

            self._count_lbl = ctk.CTkLabel(
                btn_frame,
                text="0 jobs",
                font=FONTS["body_sm"],
                text_color=COLORS["text_muted"],
            )
            self._count_lbl.pack(side="right", padx=16, pady=8)

    # ── Data ──────────────────────────────────────────────────────────────────

    def load_jobs(self, jobs: list[Job]) -> None:
        """Populate table with job list."""
        self._jobs = jobs
        self._tree.delete(*self._tree.get_children())

        for job in jobs:
            date_str = (job.posted_date or job.discovered_date or "")[:10]
            self._tree.insert(
                "",
                "end",
                iid=str(job.id or ""),
                values=(
                    job.title[:50],
                    job.company[:30],
                    job.location[:25],
                    job.source,
                    date_str,
                    job.status.capitalize(),
                ),
                tags=(job.status,),
            )

        if self._show_actions and hasattr(self, "_count_lbl"):
            self._count_lbl.configure(
                text=f"{len(jobs)} job{'s' if len(jobs) != 1 else ''}"
            )

    def get_selected_job(self) -> Job | None:
        return self._selected_job

    # ── Events ────────────────────────────────────────────────────────────────

    def _on_tree_select(self, _event=None) -> None:
        sel = self._tree.selection()
        if not sel:
            self._selected_job = None
            return
        iid = sel[0]
        for job in self._jobs:
            if str(job.id) == iid:
                self._selected_job = job
                if self._on_select:
                    self._on_select(job)
                break

    def _on_double_click(self, _event=None) -> None:
        if self._selected_job and self._on_open:
            self._on_open(self._selected_job)

    def _action_open(self) -> None:
        if self._selected_job and self._on_open:
            self._on_open(self._selected_job)

    def _action_save(self) -> None:
        if self._selected_job and self._on_save:
            self._on_save(self._selected_job)

    def _action_apply(self) -> None:
        if self._selected_job and self._on_apply:
            self._on_apply(self._selected_job)
