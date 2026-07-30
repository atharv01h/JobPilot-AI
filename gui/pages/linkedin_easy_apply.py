"""
LinkedIn Easy Apply Page — provides search filters, AI title refinement, live run telemetry, and session history.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import TYPE_CHECKING

import customtkinter as ctk

from config.constants import COLORS, FONTS
from gui.widgets.stat_card import StatCard

HEADING_XS = ("Inter", 12, "bold")

if TYPE_CHECKING:
    from gui.app import App


class LinkedinEasyApplyPage(ctk.CTkFrame):
    def __init__(self, master, app: App, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_primary"], **kwargs)
        self._app = app
        self._after_ids: set[str] = set()
        self._expanded_titles: list[str] = []
        self._title_checkboxes: list[ctk.CTkCheckBox] = []
        self._is_running = False

        self._build()
        self.load_preferences()

        # Connect to console logs update loops
        self._poll_logs()

    def safe_after(self, delay_ms: int, callback) -> str:
        if not self.winfo_exists():
            return ""
        aid = super().after(delay_ms, callback)
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
        self.grid_rowconfigure(1, weight=1)

        # Header Row
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=32, pady=(24, 0), sticky="ew")

        ctk.CTkLabel(
            header,
            text="⚡ LinkedIn Easy Apply",
            font=FONTS["heading_xl"],
            text_color=COLORS["text_primary"],
        ).pack(side="left")

        # Tabview Layout
        self._tabview = ctk.CTkTabview(self, fg_color="transparent")
        self._tabview.grid(row=1, column=0, padx=32, pady=(0, 20), sticky="nsew")

        self._tab_prefs = self._tabview.add("Preferences & AI Refinement")
        self._tab_dashboard = self._tabview.add("Live Run Dashboard")

        self._build_preferences_tab()
        self._build_dashboard_tab()

    # ── Preferences & AI Tab ──────────────────────────────────────────────────

    def _build_preferences_tab(self) -> None:
        self._tab_prefs.grid_columnconfigure(0, weight=1)
        self._tab_prefs.grid_columnconfigure(1, weight=1)
        self._tab_prefs.grid_rowconfigure(0, weight=1)

        # Left: Search preferences Form
        left_scroll = ctk.CTkScrollableFrame(
            self._tab_prefs,
            fg_color=COLORS["bg_card"],
            corner_radius=16,
            border_width=1,
            border_color=COLORS["border"],
        )
        left_scroll.grid(row=0, column=0, padx=(0, 10), pady=10, sticky="nsew")
        left_scroll.grid_columnconfigure(1, weight=1)

        # Section Header
        ctk.CTkLabel(
            left_scroll,
            text="🔍  Job Search Preferences",
            font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"],
        ).grid(row=0, column=0, columnspan=2, padx=20, pady=(16, 12), sticky="w")

        # Job Titles
        self._ent_titles = self._add_form_entry(
            left_scroll,
            1,
            "Job Titles (Comma Separated):",
            "e.g. Software Engineer, Developer",
        )

        # Skills
        self._ent_skills = self._add_form_entry(
            left_scroll, 2, "Preferred Skills:", "e.g. Python, Playwright, SQL"
        )

        # Keywords Include & Exclude
        self._ent_include = self._add_form_entry(
            left_scroll, 3, "Keywords to Include:", "e.g. backend, API"
        )
        self._ent_exclude = self._add_form_entry(
            left_scroll, 4, "Keywords to Exclude:", "e.g. senior, lead"
        )

        # Locations & Companies
        self._ent_locations = self._add_form_entry(
            left_scroll, 5, "Preferred Locations:", "e.g. London, Remote"
        )
        self._ent_companies = self._add_form_entry(
            left_scroll, 6, "Preferred Companies:", "e.g. Google, Autodesk"
        )

        # Job Location Type Checkboxes
        lbl = ctk.CTkLabel(
            left_scroll,
            text="Work Modes:",
            font=FONTS["body_sm"],
            text_color=COLORS["text_secondary"],
        )
        lbl.grid(row=7, column=0, padx=20, pady=6, sticky="w")
        cb_frame = ctk.CTkFrame(left_scroll, fg_color="transparent")
        cb_frame.grid(row=7, column=1, padx=20, pady=6, sticky="w")
        self._cb_remote = ctk.CTkCheckBox(
            cb_frame, text="Remote", font=FONTS["body_sm"]
        )
        self._cb_remote.pack(side="left", padx=4)
        self._cb_hybrid = ctk.CTkCheckBox(
            cb_frame, text="Hybrid", font=FONTS["body_sm"]
        )
        self._cb_hybrid.pack(side="left", padx=4)
        self._cb_onsite = ctk.CTkCheckBox(
            cb_frame, text="On-site", font=FONTS["body_sm"]
        )
        self._cb_onsite.pack(side="left", padx=4)

        # Job Type checkboxes
        lbl2 = ctk.CTkLabel(
            left_scroll,
            text="Job Types:",
            font=FONTS["body_sm"],
            text_color=COLORS["text_secondary"],
        )
        lbl2.grid(row=8, column=0, padx=20, pady=6, sticky="w")
        cb_frame2 = ctk.CTkFrame(left_scroll, fg_color="transparent")
        cb_frame2.grid(row=8, column=1, padx=20, pady=6, sticky="w")
        self._cb_fulltime = ctk.CTkCheckBox(
            cb_frame2, text="Full Time", font=FONTS["body_sm"]
        )
        self._cb_fulltime.pack(side="left", padx=2)
        self._cb_parttime = ctk.CTkCheckBox(
            cb_frame2, text="Part Time", font=FONTS["body_sm"]
        )
        self._cb_parttime.pack(side="left", padx=2)
        self._cb_intern = ctk.CTkCheckBox(
            cb_frame2, text="Intern", font=FONTS["body_sm"]
        )
        self._cb_intern.pack(side="left", padx=2)

        # Experience & Date Posted dropdowns
        self._opt_exp = self._add_form_option(
            left_scroll,
            9,
            "Experience Level:",
            [
                "Any Level",
                "Internship",
                "Entry Level",
                "Associate",
                "Mid-Senior Level",
                "Director",
            ],
        )
        self._opt_date = self._add_form_option(
            left_scroll,
            10,
            "Date Posted:",
            ["Anytime", "Past 24 Hours", "Past Week", "Past Month"],
        )

        # Salary & Commute
        self._ent_salary = self._add_form_entry(
            left_scroll, 11, "Salary Range:", "e.g. $80,000 - $100,000"
        )
        self._ent_commute = self._add_form_entry(
            left_scroll, 12, "Max Commute Distance:", "e.g. 20 miles"
        )

        # Visa / Sponsorship
        self._cb_auth = ctk.CTkCheckBox(
            left_scroll, text="Has Work Authorization", font=FONTS["body_sm"]
        )
        self._cb_auth.grid(row=13, column=0, columnspan=2, padx=20, pady=6, sticky="w")
        self._cb_spons = ctk.CTkCheckBox(
            left_scroll, text="Requires Visa Sponsorship", font=FONTS["body_sm"]
        )
        self._cb_spons.grid(row=14, column=0, columnspan=2, padx=20, pady=6, sticky="w")
        self._cb_relocate = ctk.CTkCheckBox(
            left_scroll, text="Willing to Relocate", font=FONTS["body_sm"]
        )
        self._cb_relocate.grid(
            row=15, column=0, columnspan=2, padx=20, pady=(6, 20), sticky="w"
        )

        # Right: AI Refinement card
        right_panel = ctk.CTkFrame(
            self._tab_prefs,
            fg_color=COLORS["bg_card"],
            corner_radius=16,
            border_width=1,
            border_color=COLORS["border"],
        )
        right_panel.grid(row=0, column=1, padx=(10, 0), pady=10, sticky="nsew")
        right_panel.grid_columnconfigure(0, weight=1)
        right_panel.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(
            right_panel,
            text="🧠  AI Search Query Optimization",
            font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"],
        ).grid(row=0, column=0, padx=20, pady=(16, 4), sticky="w")

        ctk.CTkLabel(
            right_panel,
            text="Enter a base role to generate optimized semantic search titles.",
            font=FONTS["body_sm"],
            text_color=COLORS["text_muted"],
        ).grid(row=1, column=0, padx=20, pady=(0, 12), sticky="w")

        # Seed title input
        refine_frame = ctk.CTkFrame(right_panel, fg_color="transparent")
        refine_frame.grid(row=2, column=0, padx=20, pady=6, sticky="ew")
        refine_frame.grid_columnconfigure(0, weight=1)

        self._ent_seed = ctk.CTkEntry(
            refine_frame,
            placeholder_text="e.g. Java Developer",
            font=FONTS["body_md"],
            height=36,
        )
        self._ent_seed.grid(row=0, column=0, padx=(0, 8), sticky="ew")

        self._btn_refine = ctk.CTkButton(
            refine_frame,
            text="Optimize Search",
            font=FONTS["heading_sm"],
            fg_color=COLORS["accent_primary"],
            hover_color=COLORS["bg_hover"],
            command=self._on_ai_refine,
            height=36,
        )
        self._btn_refine.grid(row=0, column=1, sticky="e")

        # Refined titles container
        self._refined_scroll = ctk.CTkScrollableFrame(
            right_panel,
            fg_color=COLORS["bg_secondary"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
        )
        self._refined_scroll.grid(
            row=3, column=0, padx=20, pady=(10, 20), sticky="nsew"
        )
        self._refined_scroll.grid_columnconfigure(0, weight=1)

        self._refine_msg = ctk.CTkLabel(
            self._refined_scroll,
            text="No refined titles yet. Type a query above.",
            font=FONTS["body_sm"],
            text_color=COLORS["text_muted"],
        )
        self._refine_msg.grid(row=0, column=0, pady=40)

    def _add_form_entry(
        self, parent: ctk.CTkFrame, row: int, label: str, placeholder: str
    ) -> ctk.CTkEntry:
        lbl = ctk.CTkLabel(
            parent,
            text=label,
            font=FONTS["body_sm"],
            text_color=COLORS["text_secondary"],
        )
        lbl.grid(row=row, column=0, padx=20, pady=6, sticky="w")
        ent = ctk.CTkEntry(
            parent, placeholder_text=placeholder, font=FONTS["body_md"], height=32
        )
        ent.grid(row=row, column=1, padx=20, pady=6, sticky="ew")
        return ent

    def _add_form_option(
        self, parent: ctk.CTkFrame, row: int, label: str, values: list
    ) -> ctk.CTkOptionMenu:
        lbl = ctk.CTkLabel(
            parent,
            text=label,
            font=FONTS["body_sm"],
            text_color=COLORS["text_secondary"],
        )
        lbl.grid(row=row, column=0, padx=20, pady=6, sticky="w")
        opt = ctk.CTkOptionMenu(parent, values=values, font=FONTS["body_sm"], height=32)
        opt.grid(row=row, column=1, padx=20, pady=6, sticky="w")
        return opt

    # ── Dashboard & History Tab ───────────────────────────────────────────────

    def _build_dashboard_tab(self) -> None:
        self._tab_dashboard.grid_columnconfigure(0, weight=1)
        self._tab_dashboard.grid_columnconfigure(1, weight=1)
        self._tab_dashboard.grid_rowconfigure(1, weight=1)

        # Action / Control Bar (Row 0)
        ctrl_bar = ctk.CTkFrame(
            self._tab_dashboard,
            fg_color=COLORS["bg_card"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
        )
        ctrl_bar.grid(row=0, column=0, columnspan=2, pady=(0, 10), sticky="ew")

        self._btn_run = ctk.CTkButton(
            ctrl_bar,
            text="⚡ Start Easy Apply",
            font=FONTS["heading_sm"],
            fg_color="#1F85DE",
            hover_color="#196BAE",
            height=36,
            command=self._on_start_stop,
        )
        self._btn_run.pack(side="left", padx=16, pady=8)

        # Settings variables
        lbl_score = ctk.CTkLabel(
            ctrl_bar,
            text="Min Score:",
            font=FONTS["body_sm"],
            text_color=COLORS["text_secondary"],
        )
        lbl_score.pack(side="left", padx=(16, 4))
        self._opt_score = ctk.CTkOptionMenu(
            ctrl_bar,
            values=["85%", "80%", "75%", "70%", "60%"],
            font=FONTS["body_sm"],
            width=90,
            height=32,
        )
        self._opt_score.pack(side="left", padx=4)

        lbl_limit = ctk.CTkLabel(
            ctrl_bar,
            text="Daily Limit:",
            font=FONTS["body_sm"],
            text_color=COLORS["text_secondary"],
        )
        lbl_limit.pack(side="left", padx=(16, 4))
        self._ent_limit = ctk.CTkEntry(
            ctrl_bar, placeholder_text="40", font=FONTS["body_md"], width=50, height=32
        )
        self._ent_limit.insert(0, "40")
        self._ent_limit.pack(side="left", padx=4)

        # Left Column: Metrics and Logs
        left_side = ctk.CTkFrame(self._tab_dashboard, fg_color="transparent")
        left_side.grid(row=1, column=0, padx=(0, 8), pady=0, sticky="nsew")
        left_side.grid_columnconfigure(0, weight=1)
        left_side.grid_rowconfigure(1, weight=1)

        # Stats Card Frame
        stats_frame = ctk.CTkFrame(left_side, fg_color="transparent")
        stats_frame.grid(row=0, column=0, pady=(0, 8), sticky="ew")
        stats_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self._card_found = StatCard(
            stats_frame,
            title="Jobs Found",
            value="0",
            icon="🔍",
            subtitle="Easy Apply matched",
            accent_color=COLORS["accent_cyan"],
        )
        self._card_found.grid(row=0, column=0, padx=4, pady=4, sticky="nsew")
        self._card_matched = StatCard(
            stats_frame,
            title="Jobs Matched",
            value="0",
            icon="🧠",
            subtitle="Compatibility > Min",
            accent_color=COLORS["accent_primary"],
        )
        self._card_matched.grid(row=0, column=1, padx=4, pady=4, sticky="nsew")
        self._card_applied = StatCard(
            stats_frame,
            title="Jobs Applied",
            value="0",
            icon="✅",
            subtitle="Form submitted",
            accent_color=COLORS["accent_green"],
        )
        self._card_applied.grid(row=0, column=2, padx=4, pady=4, sticky="nsew")
        self._card_skipped = StatCard(
            stats_frame,
            title="Jobs Skipped",
            value="0",
            icon="⏭️",
            subtitle="Threshold / Issues",
            accent_color=COLORS["accent_orange"],
        )
        self._card_skipped.grid(row=0, column=3, padx=4, pady=4, sticky="nsew")

        # Live Console Logs Card
        logs_card = ctk.CTkFrame(
            left_side,
            fg_color=COLORS["bg_card"],
            corner_radius=16,
            border_width=1,
            border_color=COLORS["border"],
        )
        logs_card.grid(row=1, column=0, sticky="nsew")
        logs_card.grid_columnconfigure(0, weight=1)
        logs_card.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            logs_card,
            text="📋  Live Automation Logs",
            font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"],
        ).grid(row=0, column=0, padx=20, pady=(16, 8), sticky="w")

        self._txt_logs = ctk.CTkTextbox(
            logs_card,
            fg_color=COLORS["bg_secondary"],
            font=("Consolas", 12),
            text_color="#A9B7C6",
            wrap="word",
            border_width=0,
        )
        self._txt_logs.grid(row=1, column=0, padx=20, pady=(0, 20), sticky="nsew")
        self._txt_logs.configure(state="disabled")

        # Right Column: Run attempts & Application History
        history_card = ctk.CTkFrame(
            self._tab_dashboard,
            fg_color=COLORS["bg_card"],
            corner_radius=16,
            border_width=1,
            border_color=COLORS["border"],
        )
        history_card.grid(row=1, column=1, padx=(8, 0), pady=0, sticky="nsew")
        history_card.grid_columnconfigure(0, weight=1)
        history_card.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            history_card,
            text="📜  LinkedIn Session History",
            font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"],
        ).grid(row=0, column=0, padx=20, pady=(16, 4), sticky="w")

        # Filter and Search history bar
        hist_filter = ctk.CTkFrame(history_card, fg_color="transparent")
        hist_filter.grid(row=1, column=0, padx=20, pady=(0, 10), sticky="ew")
        hist_filter.grid_columnconfigure(0, weight=1)

        self._ent_hist_search = ctk.CTkEntry(
            hist_filter,
            placeholder_text="Filter history...",
            font=FONTS["body_sm"],
            height=30,
        )
        self._ent_hist_search.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        self._ent_hist_search.bind(
            "<KeyRelease>", lambda *_: self.refresh_history_list()
        )

        self._btn_hist_export = ctk.CTkButton(
            hist_filter,
            text="Export CSV",
            font=FONTS["body_sm"],
            height=30,
            width=90,
            fg_color=COLORS["bg_hover"],
            text_color=COLORS["text_primary"],
            command=self._on_export_history,
        )
        self._btn_hist_export.grid(row=0, column=1, sticky="e")

        self._hist_scroll = ctk.CTkScrollableFrame(
            history_card,
            fg_color=COLORS["bg_secondary"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
        )
        self._hist_scroll.grid(row=2, column=0, padx=20, pady=(0, 20), sticky="nsew")
        self._hist_scroll.grid_columnconfigure(0, weight=1)

    # ── Settings Load & Save ──────────────────────────────────────────────────

    def load_preferences(self) -> None:
        async def _load():
            from core.database import get_database

            db = get_database()
            raw = await db.get_memory("linkedin_easy_apply_preferences")
            prefs = {}
            if raw:
                try:
                    prefs = json.loads(raw)
                except Exception as _exc:
                    logger.debug("Suppressed: %s", _exc)
            if not prefs:
                prefs = {
                    "titles": "Java Developer, Software Developer, Backend Developer, Spring Boot Developer, Full Stack Developer, Associate Software Engineer, Graduate Engineer Trainee",
                    "skills": "Java, Spring Boot, REST APIs, MySQL, JDBC",
                    "include": "fresher, graduate, associate, entry, junior",
                    "exclude": "senior, lead, manager, architect, principal",
                    "locations": "Pune, Mumbai, Bangalore, Hyderabad, Chennai, Remote",
                    "companies": "",
                    "salary": "4 LPA - 8 LPA",
                    "commute": "",
                    "remote": True,
                    "hybrid": True,
                    "onsite": True,
                    "fulltime": True,
                    "parttime": False,
                    "intern": True,
                    "auth": True,
                    "spons": False,
                    "relocate": True,
                    "exp": "Entry Level",
                    "date": "Anytime",
                    "min_score": "75%",
                    "limit": 40,
                    "seed_title": "Java Developer",
                    "expanded_titles": [],
                }
            self.after(0, lambda: self._apply_preferences_to_ui(prefs))

        self._app.run_async(_load())

    def _apply_preferences_to_ui(self, prefs: dict) -> None:
        # Clear and Populate Text Entries
        self._ent_titles.delete(0, "end")
        if prefs.get("titles"):
            self._ent_titles.insert(0, prefs["titles"])

        self._ent_skills.delete(0, "end")
        if prefs.get("skills"):
            self._ent_skills.insert(0, prefs["skills"])

        self._ent_include.delete(0, "end")
        if prefs.get("include"):
            self._ent_include.insert(0, prefs["include"])

        self._ent_exclude.delete(0, "end")
        if prefs.get("exclude"):
            self._ent_exclude.insert(0, prefs["exclude"])

        self._ent_locations.delete(0, "end")
        if prefs.get("locations"):
            self._ent_locations.insert(0, prefs["locations"])

        self._ent_companies.delete(0, "end")
        if prefs.get("companies"):
            self._ent_companies.insert(0, prefs["companies"])

        self._ent_salary.delete(0, "end")
        if prefs.get("salary"):
            self._ent_salary.insert(0, prefs["salary"])

        self._ent_commute.delete(0, "end")
        if prefs.get("commute"):
            self._ent_commute.insert(0, prefs["commute"])

        # Populate Checkboxes (First deselect, then select as per preference)
        self._cb_remote.deselect()
        if prefs.get("remote"):
            self._cb_remote.select()
        self._cb_hybrid.deselect()
        if prefs.get("hybrid"):
            self._cb_hybrid.select()
        self._cb_onsite.deselect()
        if prefs.get("onsite"):
            self._cb_onsite.select()
        self._cb_fulltime.deselect()
        if prefs.get("fulltime"):
            self._cb_fulltime.select()
        self._cb_parttime.deselect()
        if prefs.get("parttime"):
            self._cb_parttime.select()
        self._cb_intern.deselect()
        if prefs.get("intern"):
            self._cb_intern.select()
        self._cb_auth.deselect()
        if prefs.get("auth"):
            self._cb_auth.select()
        self._cb_spons.deselect()
        if prefs.get("spons"):
            self._cb_spons.select()
        self._cb_relocate.deselect()
        if prefs.get("relocate"):
            self._cb_relocate.select()

        # Dropdowns
        if prefs.get("exp"):
            self._opt_exp.set(prefs["exp"])
        if prefs.get("date"):
            self._opt_date.set(prefs["date"])
        if prefs.get("min_score"):
            self._opt_score.set(prefs["min_score"])
        if prefs.get("limit"):
            self._ent_limit.delete(0, "end")
            self._ent_limit.insert(0, str(prefs["limit"]))

        # Populate Seed and Expansions
        self._ent_seed.delete(0, "end")
        if prefs.get("seed_title"):
            self._ent_seed.insert(0, prefs["seed_title"])
        if prefs.get("expanded_titles"):
            self._update_refinement_boxes(prefs["expanded_titles"])

    def get_preferences_dict(self) -> dict:
        return {
            "titles": self._ent_titles.get(),
            "skills": self._ent_skills.get(),
            "include": self._ent_include.get(),
            "exclude": self._ent_exclude.get(),
            "locations": self._ent_locations.get(),
            "companies": self._ent_companies.get(),
            "salary": self._ent_salary.get(),
            "commute": self._ent_commute.get(),
            "remote": bool(self._cb_remote.get()),
            "hybrid": bool(self._cb_hybrid.get()),
            "onsite": bool(self._cb_onsite.get()),
            "fulltime": bool(self._cb_fulltime.get()),
            "parttime": bool(self._cb_parttime.get()),
            "intern": bool(self._cb_intern.get()),
            "auth": bool(self._cb_auth.get()),
            "spons": bool(self._cb_spons.get()),
            "relocate": bool(self._cb_relocate.get()),
            "exp": self._opt_exp.get(),
            "date": self._opt_date.get(),
            "min_score": self._opt_score.get(),
            "limit": int(self._ent_limit.get() or "40"),
            "seed_title": self._ent_seed.get(),
            "expanded_titles": self._expanded_titles,
        }

    def save_preferences(self) -> None:
        prefs = self.get_preferences_dict()

        async def _save():
            from core.database import get_database

            db = get_database()
            await db.set_memory("linkedin_easy_apply_preferences", json.dumps(prefs))

        self._app.run_async(_save())

    # ── AI Refinement Logic ───────────────────────────────────────────────────

    def _on_ai_refine(self) -> None:
        seed = self._ent_seed.get().strip()
        if not seed:
            return

        self._btn_refine.configure(state="disabled", text="Optimizing...")

        async def _refine():
            from openai import AsyncOpenAI

            from config.constants import LLM_BASE_URL, LLM_MODEL
            from config.settings import get_settings

            settings = get_settings()
            if not settings.llm_api_key:
                self.after(
                    0,
                    lambda: self._show_refine_error(
                        "NVIDIA NIM API key is missing. Set it in Settings."
                    ),
                )
                return

            prompt = (
                f"Expand the seed job title '{seed}' into a JSON list of 5-7 similar professional job titles "
                "suitable for LinkedIn searches. Return ONLY a valid JSON list of strings. No markdown, no wrappers."
            )
            try:
                client = AsyncOpenAI(
                    base_url=LLM_BASE_URL, api_key=settings.llm_api_key
                )
                response = await asyncio.wait_for(
                    client.chat.completions.create(
                        model=LLM_MODEL,
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=200,
                        temperature=0.2,
                    ),
                    timeout=15.0,
                )
                text = response.choices[0].message.content.strip()
                # Clean JSON markdown blocks
                text = text.replace("```json", "").replace("```", "").strip()
                titles = json.loads(text)
                self.after(0, lambda: self._update_refinement_boxes(titles))
            except Exception as e:
                err_str = str(e)
                self.after(0, lambda: self._show_refine_error(err_str))

        self._app.run_async(_refine())

    def _show_refine_error(self, err_msg: str) -> None:
        self._btn_refine.configure(state="normal", text="Optimize Search")
        for widget in self._refined_scroll.winfo_children():
            widget.destroy()
        lbl = ctk.CTkLabel(
            self._refined_scroll,
            text=f"Error: {err_msg}",
            font=FONTS["body_sm"],
            text_color=COLORS["accent_red"],
        )
        lbl.grid(row=0, column=0, pady=20, padx=20)

    def _update_refinement_boxes(self, titles: list[str]) -> None:
        self._btn_refine.configure(state="normal", text="Optimize Search")

        # Ensure the seed title itself is included at the beginning
        seed = self._ent_seed.get().strip()
        if seed and not any(t.lower() == seed.lower() for t in titles):
            titles.insert(0, seed)

        self._expanded_titles = titles

        for widget in self._refined_scroll.winfo_children():
            widget.destroy()

        self._title_checkboxes.clear()

        if not titles:
            lbl = ctk.CTkLabel(
                self._refined_scroll, text="No titles generated.", font=FONTS["body_sm"]
            )
            lbl.grid(row=0, column=0, pady=20)
            return

        ctk.CTkLabel(
            self._refined_scroll,
            text="Select expanded job titles to include in search:",
            font=HEADING_XS,
            text_color=COLORS["text_primary"],
        ).grid(row=0, column=0, padx=12, pady=(12, 6), sticky="w")

        for idx, title in enumerate(titles):
            cb = ctk.CTkCheckBox(
                self._refined_scroll,
                text=title,
                font=FONTS["body_sm"],
                command=self._on_title_cb_changed,
            )
            cb.select()
            cb.grid(row=idx + 1, column=0, padx=12, pady=4, sticky="w")
            self._title_checkboxes.append(cb)

        # Update main Titles entry
        self._sync_titles_entry()

    def _on_title_cb_changed(self) -> None:
        self._sync_titles_entry()
        self.save_preferences()

    def _sync_titles_entry(self) -> None:
        active_titles = []
        for cb in self._title_checkboxes:
            if cb.get():
                active_titles.append(cb.cget("text"))

        self._ent_titles.delete(0, "end")
        self._ent_titles.insert(0, ", ".join(active_titles))

    # ── Session Controls & Logging ────────────────────────────────────────────

    def _reset_run_state(self) -> None:
        self._is_running = False
        self._btn_run.configure(
            text="⚡ Start Easy Apply", fg_color="#1F85DE", hover_color="#196BAE"
        )

    def _on_start_stop(self) -> None:
        if self._is_running:
            # Stop execution
            self._is_running = False
            self._btn_run.configure(
                text="⚡ Start Easy Apply", fg_color="#1F85DE", hover_color="#196BAE"
            )

            async def _stop():
                from services.queue_manager import get_application_queue

                q = get_application_queue()
                await q.stop_processing()

            self._app.run_async(_stop())
        else:
            # Start Easy Apply
            self.save_preferences()
            self._is_running = True
            self._btn_run.configure(
                text="🛑 Stop Automation",
                fg_color=COLORS["accent_red"],
                hover_color="#B02A2A",
            )

            # Transition tab view to dashboard to watch metrics
            self._tabview.set("Live Run Dashboard")

            async def _start():
                from core.logger import get_logger

                logger = get_logger("LinkedinEasyApplyPage")
                try:
                    # Save execution mode
                    from config.settings import get_settings
                    from services.queue_manager import get_application_queue

                    settings = get_settings()
                    settings.linkedin_easy_apply_mode = (
                        True  # flag to process only LinkedIn Easy Apply jobs
                    )

                    # Fetch search preferences and launch queue run
                    q = get_application_queue()
                    await q.clear_queue()

                    # Scrape and add jobs specifically matching filters
                    from automation.browser_session_pool import get_browser_session_pool
                    from core.database import get_database
                    from scrapers.linkedin_scraper import LinkedInScraper

                    db = get_database()
                    scraper = LinkedInScraper()
                    prefs = self.get_preferences_dict()

                    # Search each title
                    titles_list = [
                        t.strip() for t in prefs["titles"].split(",") if t.strip()
                    ]
                    if not titles_list:
                        titles_list = (
                            [prefs["seed_title"]]
                            if prefs.get("seed_title")
                            else ["Software Engineer"]
                        )

                    pool = get_browser_session_pool()
                    page = await pool.get_page()

                    try:
                        for t in titles_list:
                            if not self._is_running:
                                break

                            # Search specifically for the job title itself to maximize search hits.
                            # Skills and include/exclude terms are evaluated downstream against the scraped description.
                            keywords = t

                            # Scrape jobs
                            loc = prefs.get("locations") or "United States"
                            # Pass Easy Apply mode explicitly to scraper URL
                            jobs = await scraper.scrape_playwright(page, keywords, loc)

                            # Store scraped jobs to queue directly (full evaluation happens sequentially during execution)
                            enqueued_any = False
                            for job in jobs:
                                is_dup = await db.is_duplicate(
                                    job.url, job.company, job.title
                                )
                                if is_dup:
                                    logger.debug(
                                        "LinkedIn: Duplicate job skipped: %s @ %s",
                                        job.title,
                                        job.company,
                                    )
                                    continue

                                job.status = "NEW"
                                # Insert to DB to get primary key ID
                                job_id = await db.insert_job(job)
                                if job_id:
                                    job.id = job_id
                                    # Enqueue to active run queue
                                    await q.enqueue(job)
                                    enqueued_any = True

                            # Wait for all applications from this search keyword to complete before scraping the next keyword
                            if enqueued_any:
                                logger.info(
                                    "LinkedIn: Waiting for enqueued jobs for '%s' to be applied...",
                                    t,
                                )
                                while await q.size() > 0 or q._current_job is not None:
                                    if not self._is_running:
                                        break
                                    await asyncio.sleep(5)
                    finally:
                        try:
                            await page.close()
                        except Exception as _exc:
                            logger.debug("Suppressed: %s", _exc)

                    # Reset UI run button state when fully complete
                    self.after(0, self._reset_run_state)
                except Exception as exc:
                    logger.exception(
                        "Failed to run LinkedIn Easy Apply: %s", exc
                    )
                    self.after(0, self._reset_run_state)

            self._app.run_async(_start())

    def _poll_logs(self) -> None:
        if not self.winfo_exists():
            return

        # Read last 15 lines of job_assistant.log
        log_path = "logs/job_assistant.log"
        if os.path.exists(log_path):
            try:
                with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                    tail = "".join(lines[-25:])
                    self._txt_logs.configure(state="normal")
                    self._txt_logs.delete("1.0", "end")
                    self._txt_logs.insert("1.0", tail)
                    self._txt_logs.see("end")
                    self._txt_logs.configure(state="disabled")
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

        # Also refresh dashboard metrics
        self._refresh_live_metrics()

        self.safe_after(2000, self._poll_logs)

    def _refresh_live_metrics(self) -> None:
        # Load active counts from database
        async def _load():
            from core.database import get_database

            db = get_database()
            conn = db._get_conn()
            if not conn:
                return

            cursor = await conn.execute(
                "SELECT COUNT(*), SUM(CASE WHEN status='SUBMITTED' THEN 1 ELSE 0 END), SUM(CASE WHEN status='SKIPPED' THEN 1 ELSE 0 END) FROM jobs WHERE source='LinkedIn'"
            )
            row = await cursor.fetchone()
            found = row[0] if row else 0
            applied = row[1] if row and row[1] else 0
            skipped = row[2] if row and row[2] else 0

            # Matched score check
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE source='LinkedIn' AND status='NEW'"
            )
            row_matched = await cursor.fetchone()
            matched = (row_matched[0] if row_matched else 0) + applied

            self.after(
                0, lambda: self._update_stats_cards(found, matched, applied, skipped)
            )

        self._app.run_async(_load())

    def _update_stats_cards(self, found, matched, applied, skipped) -> None:
        if not self.winfo_exists():
            return
        self._card_found.set_value(str(found))
        self._card_matched.set_value(str(matched))
        self._card_applied.set_value(str(applied))
        self._card_skipped.set_value(str(skipped))

    # ── History attempts ──────────────────────────────────────────────────────

    def refresh_history_list(self) -> None:
        filter_text = self._ent_hist_search.get().lower().strip()

        async def _load():
            from core.database import get_database

            db = get_database()
            conn = db._get_conn()
            if not conn:
                return
            cursor = await conn.execute(
                "SELECT title, company, status, discovered_date, url FROM jobs WHERE source='LinkedIn' ORDER BY discovered_date DESC LIMIT 50"
            )
            rows = await cursor.fetchall()

            history = []
            for r in rows:
                if (
                    filter_text
                    and filter_text not in r[0].lower()
                    and filter_text not in r[1].lower()
                ):
                    continue
                history.append(
                    {
                        "title": r[0],
                        "company": r[1],
                        "status": r[2],
                        "date": r[3],
                        "url": r[4],
                    }
                )
            self.after(0, lambda: self._rebuild_history_scroll(history))

        self._app.run_async(_load())

    def _rebuild_history_scroll(self, items: list) -> None:
        for widget in self._hist_scroll.winfo_children():
            widget.destroy()

        if not items:
            ctk.CTkLabel(
                self._hist_scroll,
                text="No matching LinkedIn applications found.",
                font=FONTS["body_sm"],
            ).pack(pady=20)
            return

        for idx, item in enumerate(items):
            item_frame = ctk.CTkFrame(
                self._hist_scroll,
                fg_color=COLORS["bg_card"],
                corner_radius=10,
                border_width=1,
                border_color=COLORS["border"],
            )
            item_frame.pack(fill="x", padx=4, pady=4)

            # Left side Info
            info_frame = ctk.CTkFrame(item_frame, fg_color="transparent")
            info_frame.pack(side="left", padx=12, pady=8)

            ctk.CTkLabel(
                info_frame,
                text=item["title"],
                font=HEADING_XS,
                text_color=COLORS["text_primary"],
            ).pack(anchor="w")
            ctk.CTkLabel(
                info_frame,
                text=f"{item['company']}  •  {item['date'][:10]}",
                font=FONTS["body_sm"],
                text_color=COLORS["text_muted"],
            ).pack(anchor="w")

            # Right side status
            status_color = (
                COLORS["accent_green"]
                if item["status"] == "SUBMITTED"
                else (
                    COLORS["accent_orange"]
                    if item["status"] == "SKIPPED"
                    else COLORS["accent_red"]
                )
            )
            ctk.CTkLabel(
                item_frame,
                text=item["status"],
                font=HEADING_XS,
                text_color=status_color,
            ).pack(side="right", padx=16)

    def _on_export_history(self) -> None:
        async def _do_export():
            from core.database import get_database

            db = get_database()
            conn = db._get_conn()
            if not conn:
                return
            cursor = await conn.execute(
                "SELECT title, company, location, url, status, discovered_date FROM jobs WHERE source='LinkedIn'"
            )
            rows = await cursor.fetchall()

            import csv

            out_file = "logs/linkedin_applications_history.csv"
            with open(out_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(
                    ["Title", "Company", "Location", "URL", "Status", "Date"]
                )
                for r in rows:
                    writer.writerow(list(r))
            from core.logger import get_logger

            get_logger("LinkedinEasyApplyPage").info(
                "Successfully exported history to %s", out_file
            )

        self._app.run_async(_do_export())

    def on_show(self) -> None:
        self.load_preferences()
        self.refresh_history_list()
