"""
Jobs Page — professional data grid of all scraped listings with status filters.
Includes Collapsible Search configuration drawer, AI search keyword expander,
and 300 ms debounced filter to ensure fluid UI performance.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import customtkinter as ctk

from config.constants import COLORS, FONTS
from core.logger import get_logger
from core.models import Job, JobStatus

logger = get_logger(__name__)

if TYPE_CHECKING:
    from gui.app import App


class JobsPage(ctk.CTkFrame):
    def __init__(self, master, app: App, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_primary"], **kwargs)
        self._app = app
        self._selected_ids: set[int] = set()
        self._all_jobs: list[Job] = []
        self._after_ids: set[str] = set()
        self._debounce_id: str | None = None
        self._ai_checkboxes: list[tuple[ctk.BooleanVar, ctk.StringVar]] = []
        self._drawer_expanded = False

        self._build()

        # Initial refresh
        self.refresh()

    def after(self, delay_ms: int, callback=None, *args) -> str:
        """Schedule a timer and track its ID for safe cleanup."""
        if not self.winfo_exists():
            return ""
        aid = super().after(delay_ms, callback, *args)
        self._after_ids.add(aid)
        return aid

    def destroy(self) -> None:
        """Cancel all pending timers and clean up references."""
        if self._debounce_id:
            try:
                self.after_cancel(self._debounce_id)
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)
        for aid in list(self._after_ids):
            try:
                self.after_cancel(aid)
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)
        self._after_ids.clear()
        super().destroy()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        # ── Header ───────────────────────────────────────────────────────────
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=32, pady=(24, 0), sticky="ew")

        ctk.CTkLabel(
            header,
            text="Job Listings",
            font=FONTS["heading_xl"],
            text_color=COLORS["text_primary"],
        ).pack(side="left")

        # Collapsible Settings Toggle Button
        self._toggle_drawer_btn = ctk.CTkButton(
            header,
            text="⚙️ Show Search Preferences & AI Expander",
            font=FONTS["body_md"],
            fg_color=COLORS["bg_card"],
            hover_color=COLORS["bg_hover"],
            text_color=COLORS["text_primary"],
            border_width=1,
            border_color=COLORS["border"],
            height=34,
            corner_radius=8,
            command=self._toggle_drawer,
        )
        self._toggle_drawer_btn.pack(side="right", padx=(8, 0))

        # ── Collapsible Drawer Frame (Row 1) ──────────────────────────────────
        self._drawer_frame = ctk.CTkFrame(
            self,
            fg_color=COLORS["bg_card"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
        )
        # Hidden by default

        self._build_drawer_content()

        # ── Filters Bar (Row 2) ──────────────────────────────────────────────
        filter_bar = ctk.CTkFrame(
            self,
            fg_color=COLORS["bg_card"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
        )
        filter_bar.grid(row=2, column=0, padx=32, pady=12, sticky="ew")

        ctk.CTkLabel(filter_bar, text="🔍", font=FONTS["body_md"]).pack(
            side="left", padx=(12, 6)
        )

        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._on_search_keypress())
        self._search_entry = ctk.CTkEntry(
            filter_bar,
            placeholder_text="Search Company or Role...",
            textvariable=self._search_var,
            width=220,
            height=34,
            corner_radius=6,
        )
        self._search_entry.pack(side="left", padx=6, pady=8)

        self._status_filter_var = ctk.StringVar(value="ALL")
        self._status_dropdown = ctk.CTkOptionMenu(
            filter_bar,
            variable=self._status_filter_var,
            values=[
                "ALL",
                "NEW",
                "SKIPPED",
                "FAILED",
                "APPLIED",
                "SUBMITTED",
                "REDIRECTED",
                "EXTERNAL_REQUIRED",
                "ERROR",
            ],
            fg_color=COLORS["bg_card"],
            button_color=COLORS["accent_primary"],
            width=120,
            height=34,
            command=self._debounced_apply_filters,
        )
        self._status_dropdown.pack(side="left", padx=5)

        self._sort_var = ctk.StringVar(value="Newest Discovered")
        self._sort_dropdown = ctk.CTkOptionMenu(
            filter_bar,
            variable=self._sort_var,
            values=[
                "Newest Discovered",
                "Oldest Discovered",
                "Company (A-Z)",
                "Company (Z-A)",
                "Title (A-Z)",
                "Title (Z-A)",
            ],
            fg_color=COLORS["bg_card"],
            button_color=COLORS["accent_primary"],
            width=160,
            height=34,
            command=self._debounced_apply_filters,
        )
        self._sort_dropdown.pack(side="left", padx=5)

        # Batch Actions
        btn_frame = ctk.CTkFrame(filter_bar, fg_color="transparent")
        btn_frame.pack(side="right", padx=12)

        ctk.CTkButton(
            btn_frame,
            text="📥  Import",
            fg_color=COLORS["bg_hover"],
            hover_color=COLORS["accent_primary"],
            text_color=COLORS["text_primary"],
            height=32,
            corner_radius=6,
            command=self._import_jobs,
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            btn_frame,
            text="📤  Export",
            fg_color=COLORS["bg_hover"],
            hover_color=COLORS["accent_primary"],
            text_color=COLORS["text_primary"],
            height=32,
            corner_radius=6,
            command=self._export_jobs,
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            btn_frame,
            text="⚡  Apply Selected",
            fg_color=COLORS["accent_green"],
            hover_color="#16A34A",
            height=32,
            corner_radius=6,
            command=self._batch_apply,
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            btn_frame,
            text="⏭️  Skip Selected",
            fg_color=COLORS["bg_hover"],
            hover_color=COLORS["accent_cyan"],
            height=32,
            corner_radius=6,
            command=self._batch_skip,
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            btn_frame,
            text="🗑  Delete Selected",
            fg_color="transparent",
            hover_color=COLORS["accent_red"],
            text_color=COLORS["accent_red"],
            height=32,
            corner_radius=6,
            command=self._batch_delete,
        ).pack(side="left", padx=4)

        # ── Data Grid (Row 3) ────────────────────────────────────────────────
        self._table_container = ctk.CTkFrame(
            self,
            fg_color=COLORS["bg_secondary"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
        )
        self._table_container.grid(
            row=3, column=0, padx=32, pady=(0, 20), sticky="nsew"
        )
        self._table_container.grid_columnconfigure(0, weight=1)
        self._table_container.grid_rowconfigure(1, weight=1)

        # Header Row
        self._header_row = ctk.CTkFrame(
            self._table_container, fg_color="transparent", height=32
        )
        self._header_row.grid(
            row=0, column=0, columnspan=2, padx=8, pady=4, sticky="ew"
        )

        col_configs = [
            (0, 60, "w", 0),  # Checkbox
            (1, 130, "w", 1),  # Company
            (2, 220, "w", 2),  # Role
            (3, 140, "w", 1),  # Location
            (4, 90, "w", 0),  # Website
            (5, 110, "center", 0),  # Status Badge
            (6, 210, "e", 1),  # Actions
        ]

        for col_idx, width, anchor, weight in col_configs:
            self._header_row.grid_columnconfigure(col_idx, minsize=width, weight=weight)

        headers = [
            "Select",
            "Company",
            "Role",
            "Location",
            "Website",
            "Status",
            "Actions",
        ]
        for idx, text in enumerate(headers):
            lbl = ctk.CTkLabel(
                self._header_row,
                text=text.upper(),
                font=FONTS["label"],
                text_color=COLORS["text_muted"],
                anchor="w" if idx != 5 else "center",
            )
            sticky_val = "w" if idx != 5 else ""
            if idx == 6:
                sticky_val = "e"
            lbl.grid(row=0, column=idx, padx=12, pady=4, sticky=sticky_val)

        # Table Body Frame
        self._table_body = ctk.CTkFrame(self._table_container, fg_color="transparent")
        self._table_body.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)

        self._scrollbar = ctk.CTkScrollbar(
            self._table_container, command=self._on_scrollbar_scroll
        )
        self._scrollbar.grid(row=1, column=1, sticky="ns", padx=(0, 4), pady=4)

        # Pre-create viewport widgets
        self._scroll_offset = 0
        self._current_jobs = []
        self._row_widgets = []
        self._viewport_size = 15

        for i in range(self._viewport_size):
            row_frame = ctk.CTkFrame(
                self._table_body,
                fg_color=COLORS["bg_card"] if i % 2 == 0 else COLORS["bg_secondary"],
                height=48,
                corner_radius=8,
            )
            for col_idx, width, anchor, weight in col_configs:
                row_frame.grid_columnconfigure(col_idx, minsize=width, weight=weight)

            # Checkbox
            check_var = ctk.BooleanVar()
            cb = ctk.CTkCheckBox(
                row_frame,
                text="",
                variable=check_var,
                width=16,
                height=16,
                fg_color=COLORS["accent_primary"],
            )
            cb.grid(row=0, column=0, padx=12, pady=10, sticky="w")

            # Company
            company_lbl = ctk.CTkLabel(
                row_frame,
                text="",
                font=FONTS["body_sm"],
                text_color=COLORS["text_primary"],
                anchor="w",
            )
            company_lbl.grid(row=0, column=1, padx=12, pady=8, sticky="w")

            # Role
            role_lbl = ctk.CTkLabel(
                row_frame,
                text="",
                font=FONTS["heading_sm"],
                text_color=COLORS["text_primary"],
                anchor="w",
            )
            role_lbl.grid(row=0, column=2, padx=12, pady=8, sticky="w")

            # Location
            loc_lbl = ctk.CTkLabel(
                row_frame,
                text="",
                font=FONTS["body_sm"],
                text_color=COLORS["text_secondary"],
                anchor="w",
            )
            loc_lbl.grid(row=0, column=3, padx=12, pady=8, sticky="w")

            # Website
            source_lbl = ctk.CTkLabel(
                row_frame,
                text="",
                font=FONTS["body_sm"],
                text_color=COLORS["text_muted"],
                anchor="w",
            )
            source_lbl.grid(row=0, column=4, padx=12, pady=8, sticky="w")

            # Status Badge
            badge_container = ctk.CTkFrame(
                row_frame, fg_color="transparent", width=90, height=22
            )
            badge_container.grid(row=0, column=5, padx=12, pady=8)
            badge_container.grid_propagate(False)
            badge_lbl = ctk.CTkLabel(
                badge_container,
                text="",
                font=FONTS["label"],
                text_color="#FFFFFF",
                corner_radius=6,
                width=90,
                height=22,
            )
            badge_lbl.pack(fill="both", expand=True)

            # Actions
            act_frame = ctk.CTkFrame(row_frame, fg_color="transparent")
            act_frame.grid(row=0, column=6, padx=12, pady=8, sticky="e")

            apply_btn = ctk.CTkButton(
                act_frame,
                text="Apply",
                font=FONTS["label"],
                height=24,
                width=50,
                fg_color=COLORS["accent_green"],
            )
            apply_btn.pack(side="left", padx=2)

            skip_btn = ctk.CTkButton(
                act_frame,
                text="Skip",
                font=FONTS["label"],
                height=24,
                width=50,
                fg_color=COLORS["bg_hover"],
                text_color=COLORS["text_muted"],
            )
            skip_btn.pack(side="left", padx=2)

            retry_btn = ctk.CTkButton(
                act_frame,
                text="🔄",
                font=FONTS["label"],
                height=24,
                width=30,
                fg_color="transparent",
                text_color=COLORS["accent_cyan"],
            )
            retry_btn.pack(side="left", padx=2)

            # Bind scroll events
            for w in (
                row_frame,
                cb,
                company_lbl,
                role_lbl,
                loc_lbl,
                source_lbl,
                badge_container,
                badge_lbl,
                act_frame,
                apply_btn,
                skip_btn,
                retry_btn,
            ):
                w.bind("<MouseWheel>", self._on_mousewheel)

            self._row_widgets.append(
                {
                    "frame": row_frame,
                    "cb": cb,
                    "cb_var": check_var,
                    "company_lbl": company_lbl,
                    "role_lbl": role_lbl,
                    "loc_lbl": loc_lbl,
                    "source_lbl": source_lbl,
                    "badge_lbl": badge_lbl,
                    "apply_btn": apply_btn,
                    "skip_btn": skip_btn,
                    "retry_btn": retry_btn,
                }
            )

        self._table_body.bind("<MouseWheel>", self._on_mousewheel)

    def _toggle_drawer(self) -> None:
        if self._drawer_expanded:
            self._drawer_frame.grid_remove()
            self._toggle_drawer_btn.configure(
                text="⚙️ Show Search Preferences & AI Expander"
            )
            self._drawer_expanded = False
        else:
            self._drawer_frame.grid(row=1, column=0, padx=32, pady=(12, 0), sticky="ew")
            self._toggle_drawer_btn.configure(
                text="⚙️ Hide Search Preferences & AI Expander"
            )
            self._drawer_expanded = True

    def _build_drawer_content(self) -> None:
        self._drawer_frame.grid_columnconfigure((0, 1), weight=1)

        # Left Column: Search Settings Form
        form_frame = ctk.CTkFrame(self._drawer_frame, fg_color="transparent")
        form_frame.grid(row=0, column=0, padx=16, pady=16, sticky="nsew")
        form_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            form_frame,
            text="🔍 Search Criteria",
            font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"],
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        # Load settings once
        from config.settings import get_settings

        settings = get_settings()

        # Title
        ctk.CTkLabel(
            form_frame,
            text="Job Title:",
            font=FONTS["body_sm"],
            text_color=COLORS["text_secondary"],
        ).grid(row=1, column=0, sticky="w", pady=4)
        self._title_input = ctk.CTkEntry(
            form_frame, height=28, placeholder_text="e.g. Software Engineer"
        )
        self._title_input.grid(row=1, column=1, sticky="ew", pady=4, padx=(8, 0))
        if settings.search_title:
            self._title_input.insert(0, settings.search_title)
        elif settings.keywords:
            self._title_input.insert(0, settings.keywords[0])

        # Category
        ctk.CTkLabel(
            form_frame,
            text="Category:",
            font=FONTS["body_sm"],
            text_color=COLORS["text_secondary"],
        ).grid(row=2, column=0, sticky="w", pady=4)
        self._category_input = ctk.CTkEntry(
            form_frame, height=28, placeholder_text="e.g. IT, Engineering"
        )
        self._category_input.grid(row=2, column=1, sticky="ew", pady=4, padx=(8, 0))
        if settings.search_category:
            self._category_input.insert(0, settings.search_category)

        # Location & Country
        loc_frame = ctk.CTkFrame(form_frame, fg_color="transparent")
        loc_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=4)
        loc_frame.grid_columnconfigure((1, 3), weight=1)

        ctk.CTkLabel(
            loc_frame,
            text="Location:",
            font=FONTS["body_sm"],
            text_color=COLORS["text_secondary"],
        ).grid(row=0, column=0, sticky="w")
        self._location_input = ctk.CTkEntry(
            loc_frame, height=28, placeholder_text="e.g. Pune"
        )
        self._location_input.grid(row=0, column=1, sticky="ew", padx=(8, 12))
        if settings.search_location:
            self._location_input.insert(0, settings.search_location)
        elif settings.locations:
            self._location_input.insert(0, settings.locations[0])

        ctk.CTkLabel(
            loc_frame,
            text="Country:",
            font=FONTS["body_sm"],
            text_color=COLORS["text_secondary"],
        ).grid(row=0, column=2, sticky="w")
        self._country_input = ctk.CTkEntry(
            loc_frame, height=28, placeholder_text="e.g. India"
        )
        self._country_input.grid(row=0, column=3, sticky="ew", padx=(8, 0))
        if settings.search_country:
            self._country_input.insert(0, settings.search_country)

        # Dropdowns: Job Type, Experience Level, Work Mode
        drop_frame = ctk.CTkFrame(form_frame, fg_color="transparent")
        drop_frame.grid(row=4, column=0, columnspan=2, sticky="ew", pady=4)
        drop_frame.grid_columnconfigure((0, 1, 2), weight=1)

        # Job Type
        self._job_type_var = ctk.StringVar(value=settings.search_job_type or "All")
        ctk.CTkLabel(
            drop_frame,
            text="Job Type:",
            font=FONTS["label"],
            text_color=COLORS["text_secondary"],
        ).grid(row=0, column=0, sticky="w")
        self._job_type_dropdown = ctk.CTkOptionMenu(
            drop_frame,
            variable=self._job_type_var,
            values=["All", "Full-time", "Internship", "Contract", "Part-time"],
            height=28,
            fg_color=COLORS["bg_secondary"],
            button_color=COLORS["accent_primary"],
        )
        self._job_type_dropdown.grid(
            row=1, column=0, sticky="ew", padx=(0, 8), pady=(2, 0)
        )

        # Experience
        self._experience_var = ctk.StringVar(value=settings.search_experience or "All")
        ctk.CTkLabel(
            drop_frame,
            text="Experience:",
            font=FONTS["label"],
            text_color=COLORS["text_secondary"],
        ).grid(row=0, column=1, sticky="w")
        self._experience_dropdown = ctk.CTkOptionMenu(
            drop_frame,
            variable=self._experience_var,
            values=["All", "Fresh/Entry (0-2 yrs)", "Mid (3-5 yrs)", "Senior (5+ yrs)"],
            height=28,
            fg_color=COLORS["bg_secondary"],
            button_color=COLORS["accent_primary"],
        )
        self._experience_dropdown.grid(
            row=1, column=1, sticky="ew", padx=4, pady=(2, 0)
        )

        # Work Mode
        self._work_mode_var = ctk.StringVar(value=settings.search_work_mode or "All")
        ctk.CTkLabel(
            drop_frame,
            text="Work Mode:",
            font=FONTS["label"],
            text_color=COLORS["text_secondary"],
        ).grid(row=0, column=2, sticky="w")
        self._work_mode_dropdown = ctk.CTkOptionMenu(
            drop_frame,
            variable=self._work_mode_var,
            values=["All", "Remote", "Hybrid", "Onsite"],
            height=28,
            fg_color=COLORS["bg_secondary"],
            button_color=COLORS["accent_primary"],
        )
        self._work_mode_dropdown.grid(
            row=1, column=2, sticky="ew", padx=(8, 0), pady=(2, 0)
        )

        # Salary & Companies
        ctk.CTkLabel(
            form_frame,
            text="Salary Range:",
            font=FONTS["body_sm"],
            text_color=COLORS["text_secondary"],
        ).grid(row=5, column=0, sticky="w", pady=4)
        self._salary_input = ctk.CTkEntry(
            form_frame,
            height=28,
            placeholder_text="e.g. $80,000 - $120,000 / 12-18 LPA",
        )
        self._salary_input.grid(row=5, column=1, sticky="ew", pady=4, padx=(8, 0))
        if settings.search_salary:
            self._salary_input.insert(0, settings.search_salary)

        ctk.CTkLabel(
            form_frame,
            text="Preferred Co's:",
            font=FONTS["body_sm"],
            text_color=COLORS["text_secondary"],
        ).grid(row=6, column=0, sticky="w", pady=4)
        self._pref_companies_input = ctk.CTkEntry(
            form_frame,
            height=28,
            placeholder_text="e.g. Google, NVIDIA (comma separated)",
        )
        self._pref_companies_input.grid(
            row=6, column=1, sticky="ew", pady=4, padx=(8, 0)
        )
        if settings.search_preferred_companies:
            self._pref_companies_input.insert(0, settings.search_preferred_companies)

        ctk.CTkLabel(
            form_frame,
            text="Blacklist Co's:",
            font=FONTS["body_sm"],
            text_color=COLORS["text_secondary"],
        ).grid(row=7, column=0, sticky="w", pady=4)
        self._blacklist_companies_input = ctk.CTkEntry(
            form_frame, height=28, placeholder_text="e.g. BadCorp, SpamInc"
        )
        self._blacklist_companies_input.grid(
            row=7, column=1, sticky="ew", pady=4, padx=(8, 0)
        )
        if settings.search_blacklisted_companies:
            self._blacklist_companies_input.insert(
                0, settings.search_blacklisted_companies
            )

        # Portals Checklist (Grid)
        portals_frame = ctk.CTkFrame(form_frame, fg_color="transparent")
        portals_frame.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ctk.CTkLabel(
            portals_frame,
            text="Websites to Search:",
            font=FONTS["label"],
            text_color=COLORS["text_secondary"],
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=4)

        portals_list = [
            ("LinkedIn", "linkedin"),
            ("Indeed", "indeed"),
            ("Naukri", "naukri"),
            ("Foundit", "foundit"),
            ("Glassdoor", "glassdoor"),
            ("Wellfound", "wellfound"),
            ("Greenhouse", "greenhouse"),
            ("Lever", "lever"),
            ("Workday", "workday"),
            ("Custom Websites", "custom"),
        ]
        self._web_checkboxes: dict[str, ctk.BooleanVar] = {}
        for idx, (label, key) in enumerate(portals_list):
            row_idx = (idx // 3) + 1
            col_idx = idx % 3
            var = ctk.BooleanVar(value=(key in settings.search_portals))
            chk = ctk.CTkCheckBox(
                portals_frame,
                text=label,
                variable=var,
                font=FONTS["body_sm"],
                height=20,
            )
            chk.grid(row=row_idx, column=col_idx, sticky="w", pady=3, padx=(0, 10))
            self._web_checkboxes[key] = var

        # Right Column: AI Expander Panel
        ai_frame = ctk.CTkFrame(
            self._drawer_frame, fg_color="transparent", border_width=0
        )
        ai_frame.grid(row=0, column=1, padx=16, pady=16, sticky="nsew")
        ai_frame.grid_columnconfigure(0, weight=1)
        ai_frame.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            ai_frame,
            text="🤖 AI Keywords Search Expansion",
            font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"],
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))

        # Base Expander Title input
        exp_input_frame = ctk.CTkFrame(ai_frame, fg_color="transparent")
        exp_input_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        exp_input_frame.grid_columnconfigure(0, weight=1)

        self._ai_base_title_input = ctk.CTkEntry(
            exp_input_frame, height=32, placeholder_text="e.g. Software Engineer"
        )
        self._ai_base_title_input.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        if settings.keywords:
            self._ai_base_title_input.insert(0, settings.keywords[0])

        self._ai_expand_btn = ctk.CTkButton(
            exp_input_frame,
            text="🤖 AI Expand",
            font=FONTS["body_sm"],
            fg_color=COLORS["accent_primary"],
            hover_color=COLORS["accent_secondary"],
            height=32,
            width=110,
            command=self._expand_ai_keywords,
        )
        self._ai_expand_btn.grid(row=0, column=1, sticky="e")

        # Scrollable checklist for expanded keywords
        self._ai_scroll = ctk.CTkScrollableFrame(
            ai_frame,
            fg_color=COLORS["bg_secondary"],
            corner_radius=8,
            border_width=1,
            border_color=COLORS["border"],
            height=160,
        )
        self._ai_scroll.grid(row=2, column=0, sticky="nsew", pady=4)
        self._ai_scroll.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self._ai_scroll,
            text="AI expansions checklist will appear here.",
            font=FONTS["body_sm"],
            text_color=COLORS["text_muted"],
        ).pack(pady=40)

        # Scheduler and Trigger Buttons Row
        action_row = ctk.CTkFrame(self._drawer_frame, fg_color="transparent")
        action_row.grid(
            row=1, column=0, columnspan=2, padx=16, pady=(0, 16), sticky="ew"
        )
        action_row.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(
            action_row,
            text="🕒 Auto Search Interval:",
            font=FONTS["body_sm"],
            text_color=COLORS["text_secondary"],
        ).grid(row=0, column=0, sticky="w", padx=(0, 8))

        self._scheduler_val = ctk.StringVar(value="Manual")
        self._scheduler_menu = ctk.CTkOptionMenu(
            action_row,
            variable=self._scheduler_val,
            values=["Manual", "30", "60", "120", "Every Hour", "Daily", "Weekly"],
            height=32,
            width=120,
            fg_color=COLORS["bg_secondary"],
            button_color=COLORS["accent_primary"],
            command=self._on_scheduler_interval_changed,
        )
        self._scheduler_menu.grid(row=0, column=1, sticky="w")
        # Load from config settings if exists
        if settings.scheduler_interval:
            self._scheduler_val.set(settings.scheduler_interval)

        # Auto Search switch
        self._auto_search_enabled_var = ctk.BooleanVar(
            value=settings.auto_search_enabled
        )
        self._auto_search_switch = ctk.CTkSwitch(
            action_row,
            text="Auto Search",
            variable=self._auto_search_enabled_var,
            font=FONTS["body_sm"],
            command=self._on_auto_search_toggle,
        )
        self._auto_search_switch.grid(row=0, column=2, padx=(16, 0), sticky="w")

        # Save Search Profile button
        self._save_profile_btn = ctk.CTkButton(
            action_row,
            text="💾 Save Search Profile",
            font=FONTS["body_sm"],
            fg_color=COLORS["bg_hover"],
            hover_color=COLORS["accent_primary"],
            text_color=COLORS["text_primary"],
            height=32,
            width=150,
            command=self._save_search_profile,
        )
        self._save_profile_btn.grid(row=0, column=4, padx=(8, 0), sticky="e")

        self._search_jobs_btn = ctk.CTkButton(
            action_row,
            text="🔍  Start Search & Apply",
            font=FONTS["heading_sm"],
            fg_color=COLORS["accent_green"],
            hover_color="#16A34A",
            height=36,
            width=220,
            command=self.start_search_flow,
        )
        self._search_jobs_btn.grid(row=0, column=5, sticky="e")

    def _on_scheduler_interval_changed(self, val: str) -> None:
        try:
            from services.scheduler_service import get_scheduler

            scheduler = get_scheduler()
            scheduler.apply_interval(val)

            # Persist to settings
            from config.settings import get_settings

            settings = get_settings()
            settings.scheduler_interval = val
            settings.save()
            logger.info("JobsPage: Scheduler interval set to %s and persisted.", val)
        except Exception as e:
            logger.error("JobsPage: Failed to apply scheduler interval: %s", e)

    def _on_auto_search_toggle(self) -> None:
        try:
            from services.scheduler_service import get_scheduler

            scheduler = get_scheduler()
            enabled = self._auto_search_enabled_var.get()

            # Persist to settings
            from config.settings import get_settings

            settings = get_settings()
            settings.auto_search_enabled = enabled
            settings.save()

            if enabled:
                scheduler.start()
                scheduler.apply_interval(self._scheduler_val.get())
                logger.info("JobsPage: Auto Search enabled.")
            else:
                scheduler.stop()
                logger.info("JobsPage: Auto Search disabled.")
        except Exception as e:
            logger.error("JobsPage: Failed to toggle auto search: %s", e)

    def _save_search_profile(self) -> None:
        try:
            from config.settings import get_settings

            settings = get_settings()

            # Collect preferences from UI elements
            settings.search_title = self._title_input.get().strip()
            settings.search_category = self._category_input.get().strip()
            settings.search_location = self._location_input.get().strip()
            settings.search_country = self._country_input.get().strip()
            settings.search_job_type = self._job_type_var.get()
            settings.search_experience = self._experience_var.get()
            settings.search_work_mode = self._work_mode_var.get()
            settings.search_salary = self._salary_input.get().strip()
            settings.search_preferred_companies = (
                self._pref_companies_input.get().strip()
            )
            settings.search_blacklisted_companies = (
                self._blacklist_companies_input.get().strip()
            )
            settings.search_portals = [
                key for key, var in self._web_checkboxes.items() if var.get()
            ]
            settings.auto_search_enabled = self._auto_search_enabled_var.get()
            settings.scheduler_interval = self._scheduler_val.get()

            settings.save()

            from gui.widgets.dialogs import MessageDialog

            MessageDialog(
                self._app,
                title="Profile Saved",
                message="Search preferences profile saved successfully!",
                icon="✓",
            )
            logger.info(
                "JobsPage: Search preferences profile persisted to settings.json."
            )
        except Exception as e:
            logger.error("JobsPage: Failed to save search profile: %s", e)

    def _expand_ai_keywords(self) -> None:
        base_title = self._ai_base_title_input.get().strip()
        if not base_title:
            from gui.widgets.dialogs import MessageDialog

            MessageDialog(
                self._app,
                title="Error",
                message="Please enter a base job title to expand.",
                icon="❌",
            )
            return

        self._ai_expand_btn.configure(state="disabled", text="Expanding...")

        async def run():
            from services.ai_search_service import get_ai_search_service

            try:
                expansions = await get_ai_search_service().expand_title(base_title)
                self.after(0, lambda: self._show_ai_expansions(expansions))
            except Exception as e:
                logger.error("Failed expanding keywords: %s", e)
                self.after(
                    0,
                    lambda: self._ai_expand_btn.configure(
                        state="normal", text="🤖 AI Expand"
                    ),
                )

        self._app.run_async(run())

    def _show_ai_expansions(self, expansions: list[dict[str, Any]]) -> None:
        if not self.winfo_exists():
            return
        self._ai_expand_btn.configure(state="normal", text="🤖 AI Expand")

        # Clear scroll
        for child in self._ai_scroll.winfo_children():
            child.destroy()

        self._ai_checkboxes.clear()

        if not expansions:
            ctk.CTkLabel(
                self._ai_scroll,
                text="No expansions generated by AI.",
                font=FONTS["body_sm"],
                text_color=COLORS["text_muted"],
            ).pack(pady=40)
            return

        for idx, item in enumerate(expansions):
            title = item.get("title", "")
            conf = item.get("confidence", 0.0)

            row_frame = ctk.CTkFrame(self._ai_scroll, fg_color="transparent")
            row_frame.pack(fill="x", pady=2, padx=4)

            chk_var = ctk.BooleanVar(value=True)
            chk = ctk.CTkCheckBox(
                row_frame, text="", variable=chk_var, width=16, height=16
            )
            chk.pack(side="left", padx=(0, 6))

            title_var = ctk.StringVar(value=title)
            ent = ctk.CTkEntry(
                row_frame,
                textvariable=title_var,
                font=FONTS["body_sm"],
                height=24,
                fg_color=COLORS["bg_secondary"],
                border_width=1,
                border_color=COLORS["border"],
            )
            ent.pack(side="left", fill="x", expand=True)

            lbl = ctk.CTkLabel(
                row_frame,
                text=f"({conf:.2f})",
                font=FONTS["label"],
                text_color=COLORS["text_muted"],
            )
            lbl.pack(side="right", padx=(6, 0))

            self._ai_checkboxes.append((chk_var, title_var))

    def _on_search_keypress(self) -> None:
        if self._debounce_id:
            try:
                self.after_cancel(self._debounce_id)
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)
        self._debounce_id = self.after(300, self._apply_filters)

    def _render_jobs(self, jobs: list[Job]) -> None:
        self._current_jobs = jobs
        self._update_viewport()

    def _debounced_apply_filters(self, _=None) -> None:
        if self._debounce_id:
            try:
                self.after_cancel(self._debounce_id)
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)
        self._debounce_id = self.after(300, self._apply_filters)

    def _on_scrollbar_scroll(self, *args) -> None:
        if not self._current_jobs:
            return
        if len(args) >= 2 and args[0] == "moveto":
            pos = float(args[1])
            max_offset = max(0, len(self._current_jobs) - self._viewport_size)
            self._scroll_offset = int(pos * max_offset)
            self._update_viewport()

    def _on_mousewheel(self, event) -> None:
        if not self._current_jobs:
            return
        delta = -1 if event.delta > 0 else 1
        max_offset = max(0, len(self._current_jobs) - self._viewport_size)
        new_offset = self._scroll_offset + delta
        if 0 <= new_offset <= max_offset:
            self._scroll_offset = new_offset
            self._update_viewport()

    def _update_viewport(self) -> None:
        if not self.winfo_exists():
            return

        jobs = self._current_jobs
        n = self._viewport_size
        max_offset = max(0, len(jobs) - n)
        self._scroll_offset = min(self._scroll_offset, max_offset)
        self._scroll_offset = max(self._scroll_offset, 0)

        status_colors = {
            JobStatus.NEW: COLORS["accent_primary"],
            JobStatus.APPLIED: COLORS["accent_green"],
            JobStatus.SUBMITTED: COLORS["accent_green"],
            JobStatus.FAILED: COLORS["accent_red"],
            JobStatus.SKIPPED: COLORS["accent_cyan"],
            JobStatus.REDIRECTED: COLORS["accent_orange"],
            JobStatus.EXTERNAL_REQUIRED: COLORS["accent_orange"],
            JobStatus.ERROR: COLORS["accent_red"],
        }

        for i in range(n):
            widget_dict = self._row_widgets[i]
            row_frame = widget_dict["frame"]
            job_idx = self._scroll_offset + i

            if job_idx < len(jobs):
                job = jobs[job_idx]
                row_frame.pack(fill="x", padx=8, pady=2)

                # Checkbox
                cb_var = widget_dict["cb_var"]
                cb_var.set(job.id in self._selected_ids)
                widget_dict["cb"].configure(
                    command=lambda jid=job.id, var=cb_var: self._toggle_selection(
                        jid, var.get()
                    )
                )

                # Text fields
                comp_text = job.company or ""
                widget_dict["company_lbl"].configure(
                    text=(comp_text[:20] + "...") if len(comp_text) > 20 else comp_text
                )
                role_text = job.title or ""
                widget_dict["role_lbl"].configure(
                    text=(role_text[:24] + "...") if len(role_text) > 24 else role_text
                )
                loc_text = job.location or "Remote"
                widget_dict["loc_lbl"].configure(
                    text=(loc_text[:16] + "...") if len(loc_text) > 16 else loc_text
                )
                widget_dict["source_lbl"].configure(text=job.source or "web")

                # Badge
                color = status_colors.get(job.status, COLORS["text_muted"])
                status_text = (
                    job.status.value
                    if isinstance(job.status, JobStatus)
                    else str(job.status)
                )
                widget_dict["badge_lbl"].configure(text=status_text, fg_color=color)

                # Buttons
                widget_dict["apply_btn"].configure(
                    command=lambda j=job: self._single_apply(j)
                )
                widget_dict["skip_btn"].configure(
                    command=lambda jid=job.id: self._single_skip(jid)
                )
                widget_dict["retry_btn"].configure(
                    command=lambda jid=job.id: self._single_retry(jid)
                )
            else:
                row_frame.pack_forget()

        if len(jobs) <= n:
            self._scrollbar.set(0.0, 1.0)
        else:
            first = self._scroll_offset / len(jobs)
            last = (self._scroll_offset + n) / len(jobs)
            self._scrollbar.set(first, last)

    def _toggle_selection(self, job_id: int, is_selected: bool) -> None:
        if is_selected:
            self._selected_ids.add(job_id)
        else:
            self._selected_ids.discard(job_id)

    def _apply_filters(self) -> None:
        if not self.winfo_exists():
            return
        q = self._search_var.get().lower().strip()
        status = self._status_filter_var.get()

        filtered = list(self._all_jobs)
        if q:
            filtered = [
                j for j in filtered if q in j.company.lower() or q in j.title.lower()
            ]
        if status != "ALL":
            filtered = [
                j for j in filtered if j.status.value == status or j.status == status
            ]

        # Sorting logic
        sort_mode = self._sort_var.get()
        if sort_mode == "Newest Discovered":
            filtered.sort(key=lambda x: x.discovered_date or "", reverse=True)
        elif sort_mode == "Oldest Discovered":
            filtered.sort(key=lambda x: x.discovered_date or "")
        elif sort_mode == "Company (A-Z)":
            filtered.sort(key=lambda x: x.company.lower() if x.company else "")
        elif sort_mode == "Company (Z-A)":
            filtered.sort(
                key=lambda x: x.company.lower() if x.company else "", reverse=True
            )
        elif sort_mode == "Title (A-Z)":
            filtered.sort(key=lambda x: x.title.lower() if x.title else "")
        elif sort_mode == "Title (Z-A)":
            filtered.sort(
                key=lambda x: x.title.lower() if x.title else "", reverse=True
            )

        self._render_jobs(filtered)

    def refresh(self) -> None:
        """Fetch all jobs from the database."""

        async def _load():
            from core.database import get_database

            db = get_database()
            jobs = await db.get_all_jobs()
            self._all_jobs = jobs
            self.after(0, self._apply_filters)

        self._app.run_async(_load())

    def start_search_flow(self) -> None:
        """Called when Search button is clicked. Gathers filters and triggers background search."""
        self._search_jobs_btn.configure(state="disabled", text="🔍 Searching...")

        # Collect checked search keywords
        keywords = []
        base_title = self._title_input.get().strip()
        if base_title:
            keywords.append(base_title)

        # Add all checked AI expanded titles
        for chk_var, title_var in self._ai_checkboxes:
            if chk_var.get():
                t = title_var.get().strip()
                if t:
                    keywords.append(t)

        if not keywords:
            from gui.widgets.dialogs import MessageDialog

            MessageDialog(
                self._app,
                title="Error",
                message="Please select/enter at least one job title to search.",
                icon="❌",
            )
            self._search_jobs_btn.configure(
                state="normal", text="🔍  Start Search & Apply"
            )
            return

        locations = []
        loc = self._location_input.get().strip()
        if loc:
            locations.append(loc)

        sources = [key for key, var in self._web_checkboxes.items() if var.get()]
        if not sources:
            from gui.widgets.dialogs import MessageDialog

            MessageDialog(
                self._app,
                title="Error",
                message="Please check at least one website source to search.",
                icon="❌",
            )
            self._search_jobs_btn.configure(
                state="normal", text="🔍  Start Search & Apply"
            )
            return

        job_category = self._category_input.get().strip() or None
        job_type = self._job_type_var.get()
        work_mode = self._work_mode_var.get()
        country = self._country_input.get().strip() or None
        salary_range = self._salary_input.get().strip() or None

        pref_comps = [
            c.strip() for c in self._pref_companies_input.get().split(",") if c.strip()
        ]
        blacklist_comps = [
            c.strip()
            for c in self._blacklist_companies_input.get().split(",")
            if c.strip()
        ]

        async def run_search():
            from services.job_service import get_job_service

            js = get_job_service()
            try:
                await js.search_jobs(
                    keywords=keywords,
                    locations=locations,
                    sources=sources,
                    job_category=job_category,
                    job_type=job_type,
                    work_mode=work_mode,
                    country=country,
                    salary_range=salary_range,
                    preferred_companies=pref_comps,
                    blacklist_companies=blacklist_comps,
                    progress_callback=lambda msg: logger.info("Scraper: %s", msg),
                )
            except Exception as e:
                logger.error("Search flow execution failed: %s", e)
            finally:
                self.after(
                    0,
                    lambda: self._search_jobs_btn.configure(
                        state="normal", text="🔍  Start Search & Apply"
                    ),
                )
                self.refresh()

        self._app.run_async(run_search())

    # ── Single Actions ────────────────────────────────────────────────────────

    def _single_apply(self, job: Job) -> None:
        from services.queue_manager import get_application_queue

        self._app.run_async(get_application_queue().enqueue(job, priority=1))
        self._app._navigate("queue")

    def _single_skip(self, job_id: int) -> None:
        async def run():
            from core.database import get_database

            db = get_database()
            await db.update_job_status(job_id, JobStatus.SKIPPED)
            self.refresh()

        self._app.run_async(run())

    def _single_retry(self, job_id: int) -> None:
        async def run():
            from core.database import get_database

            db = get_database()
            await db.update_job_status(job_id, JobStatus.NEW)
            self.refresh()

        self._app.run_async(run())

    # ── Batch Actions ─────────────────────────────────────────────────────────

    def _batch_apply(self) -> None:
        if not self._selected_ids:
            return
        from services.queue_manager import get_application_queue

        job_ids = list(self._selected_ids)
        self._app.run_async(get_application_queue().apply_selected(job_ids))
        self._selected_ids.clear()
        self._app._navigate("queue")

    def _batch_skip(self) -> None:
        if not self._selected_ids:
            return

        async def run():
            from core.database import get_database

            db = get_database()
            for jid in self._selected_ids:
                await db.update_job_status(jid, JobStatus.SKIPPED)
            self._selected_ids.clear()
            self.refresh()

        self._app.run_async(run())

    def _batch_delete(self) -> None:
        if not self._selected_ids:
            return

        async def run():
            from core.database import get_database

            db = get_database()
            await db.batch_delete_jobs(list(self._selected_ids))
            self._selected_ids.clear()
            self.refresh()

        self._app.run_async(run())

    def _import_jobs(self) -> None:
        from gui.widgets.dialogs import ImportLinksDialog

        ImportLinksDialog(self._app)

    def _export_jobs(self) -> None:
        async def do_export():
            try:
                from services.job_service import get_job_service

                js = get_job_service()
                j_csv, a_csv = await js.export_csv()
                from gui.widgets.dialogs import MessageDialog

                self.after(
                    0,
                    lambda: MessageDialog(
                        self._app,
                        title="Export Success",
                        message=f"Exported successfully!\nJobs CSV: {j_csv}\nApplied CSV: {a_csv}",
                        icon="✅",
                    ),
                )
            except Exception:
                from gui.widgets.dialogs import MessageDialog

                self.after(
                    0,
                    lambda: MessageDialog(
                        self._app,
                        title="Export Failed",
                        message=f"Error exporting data: {e}",
                        icon="❌",
                    ),
                )

        self._app.run_async(do_export())

    def on_show(self) -> None:
        self.refresh()
