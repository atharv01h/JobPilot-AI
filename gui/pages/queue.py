"""
Queue Page — manage the persistent application queue (pending, completed, and failed jobs).
Includes a 300 ms debounced search/filter bar to avoid screen flicker and ensure smooth operation.
"""

from __future__ import annotations

from core.logger import get_logger

logger = get_logger(__name__)

from typing import TYPE_CHECKING

import customtkinter as ctk

from config.constants import COLORS, FONTS
from services.queue_manager import get_application_queue

if TYPE_CHECKING:
    from gui.app import App


class QueuePage(ctk.CTkFrame):
    def __init__(self, master, app: App, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_primary"], **kwargs)
        self._app = app
        self._queue_items: list[dict] = []
        self._selected_job_ids: set[int] = set()
        self._after_ids: set[str] = set()
        self._debounce_id: str | None = None
        self._build()

        # Register queue updates callback
        get_application_queue().register_callback(lambda: self.after(0, self.refresh))

        from services.state_manager import get_state_manager

        get_state_manager().register_listener(self._on_state_changed)

    def after(self, delay_ms: int, callback=None, *args) -> str:
        """Schedule a timer and track its ID for safe cleanup."""
        if not self.winfo_exists():
            return ""
        aid = super().after(delay_ms, callback, *args)
        self._after_ids.add(aid)
        return aid

    def destroy(self) -> None:
        """Cancel all pending timers and unregister listeners."""
        if self._debounce_id:
            try:
                self.after_cancel(self._debounce_id)
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)
        try:
            from services.state_manager import get_state_manager

            get_state_manager().unregister_listener(self._on_state_changed)
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)
        for aid in list(self._after_ids):
            try:
                self.after_cancel(aid)
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)
        self._after_ids.clear()
        super().destroy()

    def _on_state_changed(self) -> None:
        if self.winfo_exists():
            self.refresh()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        # ── Header & Status (Row 0) ───────────────────────────────────────────
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=32, pady=(24, 0), sticky="ew")

        ctk.CTkLabel(
            header,
            text="Application Queue",
            font=FONTS["heading_xl"],
            text_color=COLORS["text_primary"],
        ).pack(side="left")

        # Status Bar
        self._status_label = ctk.CTkLabel(
            header,
            text="Status: IDLE",
            font=FONTS["body_sm"],
            text_color=COLORS["text_muted"],
        )
        self._status_label.pack(side="right", padx=10)

        # ── Control Bar (Row 1) ───────────────────────────────────────────────
        ctrl_bar = ctk.CTkFrame(
            self,
            fg_color=COLORS["bg_card"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
        )
        ctrl_bar.grid(row=1, column=0, padx=32, pady=(12, 6), sticky="ew")

        # Row 1 Frame
        row1_frame = ctk.CTkFrame(ctrl_bar, fg_color="transparent")
        row1_frame.pack(fill="x", padx=8, pady=4)

        # Row 2 Frame
        row2_frame = ctk.CTkFrame(ctrl_bar, fg_color="transparent")
        row2_frame.pack(fill="x", padx=8, pady=4)

        # Control Buttons - Row 1
        ctk.CTkButton(
            row1_frame,
            text="⚡ Start Auto Apply",
            font=FONTS["body_sm"],
            height=30,
            width=130,
            fg_color=COLORS["accent_primary"],
            hover_color=COLORS["bg_hover"],
            command=self._start_auto_apply,
        ).pack(side="left", padx=4, pady=4)

        ctk.CTkButton(
            row1_frame,
            text="⏸ Pause",
            font=FONTS["body_sm"],
            height=30,
            width=90,
            fg_color=COLORS["bg_hover"],
            text_color=COLORS["text_primary"],
            command=self._pause_queue,
        ).pack(side="left", padx=4, pady=4)

        ctk.CTkButton(
            row1_frame,
            text="▶ Resume",
            font=FONTS["body_sm"],
            height=30,
            width=90,
            fg_color=COLORS["bg_hover"],
            text_color=COLORS["text_primary"],
            command=self._resume_queue,
        ).pack(side="left", padx=4, pady=4)

        ctk.CTkButton(
            row1_frame,
            text="🛑 Cancel Current",
            font=FONTS["body_sm"],
            height=30,
            width=130,
            fg_color=COLORS["accent_red"],
            hover_color="#B02A2A",
            command=self._cancel_current,
        ).pack(side="left", padx=4, pady=4)

        ctk.CTkButton(
            row1_frame,
            text="📦 Apply All (NEW)",
            font=FONTS["body_sm"],
            height=30,
            width=130,
            fg_color=COLORS["bg_hover"],
            text_color=COLORS["text_primary"],
            command=self._apply_all,
        ).pack(side="right", padx=4, pady=4)

        # Actions Buttons - Row 2
        ctk.CTkButton(
            row2_frame,
            text="🔄 Retry Failed",
            font=FONTS["body_sm"],
            height=30,
            width=110,
            fg_color=COLORS["bg_hover"],
            text_color=COLORS["accent_cyan"],
            command=self._retry_failed,
        ).pack(side="left", padx=4, pady=4)

        ctk.CTkButton(
            row2_frame,
            text="🗳 Retry Selected",
            font=FONTS["body_sm"],
            height=30,
            width=110,
            fg_color=COLORS["bg_hover"],
            text_color=COLORS["accent_cyan"],
            command=self._retry_selected,
        ).pack(side="left", padx=4, pady=4)

        ctk.CTkButton(
            row2_frame,
            text="✨ Apply Selected",
            font=FONTS["body_sm"],
            height=30,
            width=110,
            fg_color=COLORS["bg_hover"],
            text_color=COLORS["accent_green"],
            command=self._apply_selected,
        ).pack(side="left", padx=4, pady=4)

        ctk.CTkButton(
            row2_frame,
            text="🔍 Apply Filtered",
            font=FONTS["body_sm"],
            height=30,
            width=110,
            fg_color=COLORS["bg_hover"],
            text_color=COLORS["accent_green"],
            command=self._apply_filtered,
        ).pack(side="left", padx=4, pady=4)

        ctk.CTkButton(
            row2_frame,
            text="Clear Completed",
            font=FONTS["body_sm"],
            height=30,
            fg_color="transparent",
            text_color=COLORS["text_muted"],
            command=self._clear_completed,
        ).pack(side="right", padx=4, pady=4)

        # ── Filters Bar (Row 2) ───────────────────────────────────────────────
        filter_bar = ctk.CTkFrame(
            self,
            fg_color=COLORS["bg_card"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
        )
        filter_bar.grid(row=2, column=0, padx=32, pady=(6, 12), sticky="ew")

        ctk.CTkLabel(filter_bar, text="🔍", font=FONTS["body_md"]).pack(
            side="left", padx=(12, 6)
        )

        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._on_search_keypress())
        self._search_entry = ctk.CTkEntry(
            filter_bar,
            placeholder_text="Filter Queue by Company or Role...",
            textvariable=self._search_var,
            width=320,
            height=34,
            corner_radius=6,
        )
        self._search_entry.pack(side="left", padx=6, pady=8)

        # ── Queue Table Grid (Row 3) ──────────────────────────────────────────
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
            self._table_container, fg_color="transparent", height=28
        )
        self._header_row.grid(
            row=0, column=0, columnspan=2, padx=8, pady=4, sticky="ew"
        )

        col_configs = [
            (0, 60, "w", 0),  # Checkbox
            (1, 80, "w", 0),  # Priority
            (2, 320, "w", 1),  # Job Details
            (3, 120, "w", 0),  # Website
            (4, 130, "center", 0),  # Queue Status
            (5, 120, "w", 0),  # Added At
        ]

        for col_idx, width, anchor, weight in col_configs:
            self._header_row.grid_columnconfigure(col_idx, minsize=width, weight=weight)

        headers = [
            ("Select", "w"),
            ("Priority", "w"),
            ("Job Details", "w"),
            ("Website", "w"),
            ("Queue Status", "center"),
            ("Added At", "w"),
        ]
        for idx, (text, align) in enumerate(headers):
            lbl = ctk.CTkLabel(
                self._header_row,
                text=text.upper(),
                font=FONTS["label"],
                text_color=COLORS["text_muted"],
                anchor=align,
            )
            sticky_val = "w" if align == "w" else ""
            lbl.grid(row=0, column=idx, padx=10, pady=4, sticky=sticky_val)

        # Body Frame
        self._table_body = ctk.CTkFrame(self._table_container, fg_color="transparent")
        self._table_body.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)

        # Scrollbar
        self._scrollbar = ctk.CTkScrollbar(
            self._table_container, command=self._on_scrollbar_scroll
        )
        self._scrollbar.grid(row=1, column=1, sticky="ns", padx=(0, 4), pady=4)

        # Pre-create N = 15 viewport rows
        self._scroll_offset = 0
        self._current_items = []
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
                row_frame, text="", variable=check_var, width=16, height=16
            )
            cb.grid(row=0, column=0, padx=12, pady=8, sticky="w")

            # Priority Selector
            priority_var = ctk.StringVar(value="0")
            priority_menu = ctk.CTkOptionMenu(
                row_frame,
                variable=priority_var,
                values=["0", "1", "2", "3", "4", "5"],
                width=60,
                height=28,
                fg_color=COLORS["bg_secondary"],
                button_color=COLORS["accent_primary"],
            )
            priority_menu.grid(row=0, column=1, padx=10, pady=8, sticky="w")

            # Job Details
            details_lbl = ctk.CTkLabel(
                row_frame,
                text="",
                font=FONTS["heading_sm"],
                text_color=COLORS["text_primary"],
                anchor="w",
            )
            details_lbl.grid(row=0, column=2, padx=10, pady=8, sticky="w")

            # Website
            source_lbl = ctk.CTkLabel(
                row_frame,
                text="",
                font=FONTS["body_sm"],
                text_color=COLORS["text_secondary"],
                anchor="w",
            )
            source_lbl.grid(row=0, column=3, padx=10, pady=8, sticky="w")

            # Queue Status Badge
            badge_container = ctk.CTkFrame(
                row_frame, fg_color="transparent", width=90, height=22
            )
            badge_container.grid(row=0, column=4, padx=10, pady=8)
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

            # Added At
            added_lbl = ctk.CTkLabel(
                row_frame,
                text="",
                font=FONTS["mono"],
                text_color=COLORS["text_muted"],
                anchor="w",
            )
            added_lbl.grid(row=0, column=5, padx=10, pady=8, sticky="w")

            # Bind scroll events
            for w in (
                row_frame,
                cb,
                priority_menu,
                details_lbl,
                source_lbl,
                badge_container,
                badge_lbl,
                added_lbl,
            ):
                w.bind("<MouseWheel>", self._on_mousewheel)

            self._row_widgets.append(
                {
                    "frame": row_frame,
                    "cb": cb,
                    "cb_var": check_var,
                    "p_menu": priority_menu,
                    "p_var": priority_var,
                    "details_lbl": details_lbl,
                    "source_lbl": source_lbl,
                    "badge_lbl": badge_lbl,
                    "added_lbl": added_lbl,
                }
            )

        self._table_body.bind("<MouseWheel>", self._on_mousewheel)

    def _on_search_keypress(self) -> None:
        if self._debounce_id:
            try:
                self.after_cancel(self._debounce_id)
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)
        self._debounce_id = self.after(300, self._apply_filters)

    def _apply_filters(self) -> None:
        if not self.winfo_exists():
            return
        q = self._search_var.get().lower().strip()
        filtered = self._queue_items
        if q:
            filtered = [
                x
                for x in filtered
                if (x.get("company") and q in x["company"].lower())
                or (x.get("title") and q in x["title"].lower())
            ]
        self._render_list(filtered)

    def _render_list(self, items: list[dict]) -> None:
        self._current_items = items
        self._update_viewport()

    def _on_scrollbar_scroll(self, *args) -> None:
        if not self._current_items:
            return
        if len(args) >= 2 and args[0] == "moveto":
            pos = float(args[1])
            max_offset = max(0, len(self._current_items) - self._viewport_size)
            self._scroll_offset = int(pos * max_offset)
            self._update_viewport()

    def _on_mousewheel(self, event) -> None:
        if not self._current_items:
            return
        delta = -1 if event.delta > 0 else 1
        max_offset = max(0, len(self._current_items) - self._viewport_size)
        new_offset = self._scroll_offset + delta
        if 0 <= new_offset <= max_offset:
            self._scroll_offset = new_offset
            self._update_viewport()

    def _update_viewport(self) -> None:
        if not self.winfo_exists():
            return

        items = self._current_items
        n = self._viewport_size
        max_offset = max(0, len(items) - n)
        self._scroll_offset = min(self._scroll_offset, max_offset)
        self._scroll_offset = max(self._scroll_offset, 0)

        colors = {
            "PENDING": COLORS["text_muted"],
            "RUNNING": COLORS["accent_primary"],
            "COMPLETED": COLORS["accent_green"],
            "FAILED": COLORS["accent_red"],
        }

        for i in range(n):
            widget_dict = self._row_widgets[i]
            row_frame = widget_dict["frame"]
            item_idx = self._scroll_offset + i

            if item_idx < len(items):
                item = items[item_idx]
                row_frame.pack(fill="x", padx=8, pady=2)

                # Checkbox
                cb_var = widget_dict["cb_var"]
                cb_var.set(item["job_id"] in self._selected_job_ids)
                widget_dict["cb"].configure(
                    command=lambda jid=item["job_id"], var=cb_var: (
                        self._toggle_selection(jid, var.get())
                    )
                )

                # Priority menu
                p_var = widget_dict["p_var"]
                p_var.set(str(item["priority"]))
                widget_dict["p_menu"].configure(
                    command=lambda p, jid=item["job_id"]: self._update_priority(
                        jid, int(p)
                    )
                )

                # Details
                job_text = f"{item['title']} @ {item['company']}"
                if len(job_text) > 42:
                    job_text = job_text[:42] + "..."
                widget_dict["details_lbl"].configure(text=job_text)

                # Website
                widget_dict["source_lbl"].configure(text=item["source"] or "Generic")

                # Badge
                color = colors.get(item["status"], COLORS["text_muted"])
                widget_dict["badge_lbl"].configure(text=item["status"], fg_color=color)

                # Added At
                time_text = (
                    item["added_at"][11:19]
                    if len(item["added_at"]) > 19
                    else item["added_at"]
                )
                widget_dict["added_lbl"].configure(text=time_text)
            else:
                row_frame.pack_forget()

        if len(items) <= n:
            self._scrollbar.set(0.0, 1.0)
        else:
            first = self._scroll_offset / len(items)
            last = (self._scroll_offset + n) / len(items)
            self._scrollbar.set(first, last)

    def _toggle_selection(self, job_id: int, is_selected: bool) -> None:
        if is_selected:
            self._selected_job_ids.add(job_id)
        else:
            self._selected_job_ids.discard(job_id)

    def _update_priority(self, job_id: int, priority: int) -> None:
        self._app.run_async(get_application_queue().update_priority(job_id, priority))

    def _start_auto_apply(self) -> None:
        async def run():
            q = get_application_queue()
            await q.start_processing()

        self._app.run_async(run())

    def _pause_queue(self) -> None:
        get_application_queue().pause()
        self._status_label.configure(
            text="Status: PAUSED", text_color=COLORS["accent_orange"]
        )

    def _resume_queue(self) -> None:
        self._app.run_async(get_application_queue().resume())
        self._status_label.configure(
            text="Status: ACTIVE", text_color=COLORS["accent_green"]
        )

    def _cancel_current(self) -> None:
        self._app.run_async(get_application_queue().cancel_current())

    def _retry_failed(self) -> None:
        self._app.run_async(get_application_queue().retry_failed())

    def _retry_selected(self) -> None:
        if not self._selected_job_ids:
            return
        self._app.run_async(
            get_application_queue().retry_selected(list(self._selected_job_ids))
        )
        self._selected_job_ids.clear()
        self.refresh()

    def _apply_selected(self) -> None:
        if not self._selected_job_ids:
            return
        self._app.run_async(
            get_application_queue().apply_selected(list(self._selected_job_ids))
        )
        self._selected_job_ids.clear()
        self.refresh()

    def _apply_filtered(self) -> None:
        q = self._search_var.get().lower().strip()
        filtered_job_ids = []
        for x in self._queue_items:
            if (
                not q
                or (x.get("company") and q in x["company"].lower())
                or (x.get("title") and q in x["title"].lower())
            ):
                filtered_job_ids.append(x["job_id"])
        if filtered_job_ids:
            self._app.run_async(
                get_application_queue().retry_selected(filtered_job_ids)
            )
            self.refresh()

    def _apply_all(self) -> None:
        async def run():
            q = get_application_queue()
            await q.apply_all()
            await q.start_processing()

        self._app.run_async(run())

    def _retry_external(self) -> None:
        self._app.run_async(get_application_queue().retry_external())

    def _clear_completed(self) -> None:
        self._app.run_async(get_application_queue().clear_completed())

    def refresh(self) -> None:
        """Fetch all queue items from database."""

        async def _load():
            q = get_application_queue()
            items = await q.get_queue_items()
            self._queue_items = items

            # Count running / pending
            pending_count = sum(1 for x in items if x["status"] == "PENDING")

            from services.state_manager import AppState, get_state_manager

            stm = get_state_manager()
            snap = stm.get_snapshot()
            app_state = snap.app_state

            status_text = f"Status: {app_state}"
            color = COLORS["text_muted"]

            if app_state == AppState.APPLYING:
                status_text = f"Status: APPLYING ({pending_count} pending)"
                color = COLORS["accent_green"]
            elif app_state == AppState.SEARCHING:
                status_text = "Status: SEARCHING JOBS..."
                color = COLORS["accent_cyan"]
            elif app_state == AppState.PAUSED:
                status_text = "Status: PAUSED"
                color = COLORS["accent_orange"]
            elif app_state == AppState.COMPLETED:
                status_text = "Status: COMPLETED"
                color = COLORS["accent_green"]
            elif app_state == AppState.FAILED:
                status_text = "Status: FAILED"
                color = COLORS["accent_red"]
            elif app_state == AppState.QUEUED:
                status_text = f"Status: QUEUED ({pending_count} pending)"
                color = COLORS["accent_primary"]

            self.after(0, lambda: self._update_view(items, status_text, color))

        self._app.run_async(_load())

    def _update_view(self, items, status_text, color):
        self._apply_filters()
        self._status_label.configure(text=status_text, text_color=color)

    def on_show(self) -> None:
        self.refresh()
