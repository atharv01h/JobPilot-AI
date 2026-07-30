"""
Job detail panel — side panel showing full job information.
"""

from __future__ import annotations

import webbrowser

import customtkinter as ctk

from config.constants import COLORS, FONTS
from core.models import Job


class JobDetailPanel(ctk.CTkFrame):
    """
    Displays the selected job's full details in a side panel.
    Shows title, company, location, experience, salary, skills,
    description, and a button to open the job URL.
    """

    def __init__(self, master, **kwargs):
        super().__init__(
            master,
            fg_color=COLORS["bg_card"],
            corner_radius=16,
            border_width=1,
            border_color=COLORS["border"],
            **kwargs,
        )
        self._current_job: Job | None = None
        self._build_empty_state()

    def _build_empty_state(self) -> None:
        self._clear()
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(
            frame,
            text="📋",
            font=("Segoe UI Emoji", 40),
            text_color=COLORS["text_muted"],
        ).pack()
        ctk.CTkLabel(
            frame,
            text="Select a job to view details",
            font=FONTS["body_md"],
            text_color=COLORS["text_muted"],
        ).pack(pady=(8, 0))

    def _clear(self) -> None:
        for child in self.winfo_children():
            child.destroy()

    def show_job(self, job: Job) -> None:
        self._current_job = job
        self._clear()
        self._build_job_detail(job)

    def _build_job_detail(self, job: Job) -> None:
        # Scrollable container
        scroll = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            scrollbar_button_color=COLORS["border"],
        )
        scroll.pack(fill="both", expand=True, padx=4, pady=4)
        scroll.grid_columnconfigure(0, weight=1)

        row = 0

        # ── Header ────────────────────────────────────────────────────────────
        source_badge = ctk.CTkLabel(
            scroll,
            text=f"  {job.source}  ",
            font=FONTS["body_sm"],
            fg_color=COLORS["accent_primary"],
            text_color="#FFFFFF",
            corner_radius=6,
        )
        source_badge.grid(row=row, column=0, padx=16, pady=(16, 4), sticky="w")
        row += 1

        title_lbl = ctk.CTkLabel(
            scroll,
            text=job.title or "—",
            font=FONTS["heading_md"],
            text_color=COLORS["text_primary"],
            anchor="w",
            wraplength=320,
        )
        title_lbl.grid(row=row, column=0, padx=16, pady=(0, 2), sticky="w")
        row += 1

        company_lbl = ctk.CTkLabel(
            scroll,
            text=f"🏢  {job.company}" if job.company else "Company N/A",
            font=FONTS["body_lg"],
            text_color=COLORS["accent_secondary"],
            anchor="w",
        )
        company_lbl.grid(row=row, column=0, padx=16, pady=2, sticky="w")
        row += 1

        # ── Metadata chips ────────────────────────────────────────────────────
        meta_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        meta_frame.grid(row=row, column=0, padx=16, pady=(8, 12), sticky="w")
        row += 1

        chips = [
            (f"📍 {job.location or 'Remote'}", COLORS["accent_cyan"]),
            (f"⏱  {job.experience or 'Fresher'}", COLORS["accent_orange"]),
            (f"💰 {job.salary or 'Not disclosed'}", COLORS["accent_green"]),
        ]
        for i, (text, color) in enumerate(chips):
            ctk.CTkLabel(
                meta_frame,
                text=f"  {text}  ",
                font=FONTS["body_sm"],
                fg_color=COLORS["bg_hover"],
                text_color=color,
                corner_radius=8,
            ).grid(row=0, column=i, padx=(0, 8), pady=2)

        sep = ctk.CTkFrame(scroll, height=1, fg_color=COLORS["border"])
        sep.grid(row=row, column=0, padx=16, pady=8, sticky="ew")
        row += 1

        # ── Sections ──────────────────────────────────────────────────────────
        sections = []
        if job.skills:
            sections.append(("🛠  Required Skills", job.skills))
        if job.requirements:
            sections.append(("📌 Requirements", job.requirements))
        if job.description:
            sections.append(("📄 Description", job.description[:800]))

        for sec_title, content in sections:
            ctk.CTkLabel(
                scroll,
                text=sec_title,
                font=FONTS["heading_sm"],
                text_color=COLORS["text_secondary"],
                anchor="w",
            ).grid(row=row, column=0, padx=16, pady=(12, 4), sticky="w")
            row += 1

            ctk.CTkLabel(
                scroll,
                text=content,
                font=FONTS["body_sm"],
                text_color=COLORS["text_primary"],
                anchor="w",
                wraplength=320,
                justify="left",
            ).grid(row=row, column=0, padx=16, pady=(0, 8), sticky="w")
            row += 1

        # Dates
        if job.posted_date or job.discovered_date:
            date_text = f"Posted: {job.posted_date or 'N/A'}  |  Found: {(job.discovered_date or '')[:10]}"
            ctk.CTkLabel(
                scroll,
                text=date_text,
                font=FONTS["body_sm"],
                text_color=COLORS["text_muted"],
                anchor="w",
            ).grid(row=row, column=0, padx=16, pady=4, sticky="w")
            row += 1

        # ── Open URL button ───────────────────────────────────────────────────
        if job.url:
            btn_frame = ctk.CTkFrame(scroll, fg_color="transparent")
            btn_frame.grid(row=row, column=0, padx=16, pady=16, sticky="w")

            ctk.CTkButton(
                btn_frame,
                text="🔗  Open Job Posting",
                font=FONTS["body_md"],
                fg_color=COLORS["accent_primary"],
                hover_color=COLORS["accent_secondary"],
                corner_radius=10,
                height=38,
                command=lambda: webbrowser.open(job.url),
            ).pack(side="left", padx=(0, 8))

            ctk.CTkLabel(
                btn_frame,
                text=job.url[:50] + "…" if len(job.url) > 50 else job.url,
                font=FONTS["body_sm"],
                text_color=COLORS["text_muted"],
            ).pack(side="left")

    def clear(self) -> None:
        self._current_job = None
        self._build_empty_state()
