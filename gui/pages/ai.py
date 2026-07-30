"""
AI Page — configure LLM models, test prompts, view token usage, latencies, and AI decision cache.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import customtkinter as ctk

from config.constants import COLORS, FONTS

if TYPE_CHECKING:
    from gui.app import App


class AIPage(ctk.CTkFrame):
    def __init__(self, master, app: App, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_primary"], **kwargs)
        self._app = app
        self._build()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=32, pady=(24, 0), sticky="ew")

        ctk.CTkLabel(
            header,
            text="AI Core & Reasoning Settings",
            font=FONTS["heading_xl"],
            text_color=COLORS["text_primary"],
        ).pack(side="left")

        # Scrollable panel
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.grid(row=1, column=0, padx=32, pady=12, sticky="nsew")
        self.grid_rowconfigure(1, weight=1)
        scroll.grid_columnconfigure(0, weight=1)

        # Upper Card: Model configurations
        card_model = ctk.CTkFrame(
            scroll,
            fg_color=COLORS["bg_card"],
            corner_radius=16,
            border_width=1,
            border_color=COLORS["border"],
        )
        card_model.pack(fill="x", pady=8)
        card_model.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            card_model,
            text="Active Large Language Models",
            font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"],
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, padx=20, pady=(16, 8), sticky="w")

        self._lbl_model = self._create_row(card_model, 1, "Reasoning model:")
        self._lbl_vision = self._create_row(card_model, 2, "Vision model:")
        self._lbl_api = self._create_row(card_model, 3, "API Provider:")

        # Token & latency statistics
        card_stats = ctk.CTkFrame(
            scroll,
            fg_color=COLORS["bg_card"],
            corner_radius=16,
            border_width=1,
            border_color=COLORS["border"],
        )
        card_stats.pack(fill="x", pady=8)
        card_stats.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            card_stats,
            text="AI Decisions Cache & Usage Stats",
            font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"],
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, padx=20, pady=(16, 8), sticky="w")

        self._lbl_total_decisions = self._create_row(
            card_stats, 1, "Total Decisions Stored:"
        )
        self._lbl_cache_hits = self._create_row(card_stats, 2, "Knowledge Base Size:")
        self._lbl_lat_avg = self._create_row(card_stats, 3, "Avg LLM Latency:")

        # Prompt Test Tool (Playground)
        card_test = ctk.CTkFrame(
            scroll,
            fg_color=COLORS["bg_card"],
            corner_radius=16,
            border_width=1,
            border_color=COLORS["border"],
        )
        card_test.pack(fill="x", pady=8)

        ctk.CTkLabel(
            card_test,
            text="Test LLM Model Playground",
            font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"],
            anchor="w",
        ).pack(padx=20, pady=(16, 8), anchor="w")

        self._test_entry = ctk.CTkEntry(
            card_test,
            placeholder_text="Type a prompt question to test NVIDIA NIM model...",
            font=FONTS["body_sm"],
            height=36,
            corner_radius=8,
        )
        self._test_entry.pack(fill="x", padx=20, pady=8)

        self._test_btn = ctk.CTkButton(
            card_test,
            text="⚡  Query Model",
            fg_color=COLORS["accent_primary"],
            hover_color=COLORS["accent_secondary"],
            font=FONTS["body_sm"],
            height=32,
            width=120,
            corner_radius=6,
            command=self._test_query,
        )
        self._test_btn.pack(padx=20, pady=(0, 12), anchor="w")

        self._result_text = ctk.CTkTextbox(
            card_test,
            font=FONTS["mono"],
            height=120,
            fg_color=COLORS["bg_secondary"],
            text_color=COLORS["text_primary"],
            wrap="word",
        )
        self._result_text.pack(fill="x", padx=20, pady=(0, 20))
        self._result_text.insert("1.0", "Model response will appear here...")
        self._result_text.configure(state="disabled")

        self.refresh()

    def _create_row(self, parent: ctk.CTkFrame, row: int, label: str) -> ctk.CTkLabel:
        lbl = ctk.CTkLabel(
            parent,
            text=label,
            font=FONTS["body_sm"],
            text_color=COLORS["text_secondary"],
            anchor="w",
        )
        lbl.grid(row=row, column=0, padx=20, pady=8, sticky="w")

        val_lbl = ctk.CTkLabel(
            parent,
            text="--",
            font=FONTS["body_sm"],
            text_color=COLORS["text_primary"],
            anchor="e",
        )
        val_lbl.grid(row=row, column=1, padx=20, pady=8, sticky="e")
        return val_lbl

    def _test_query(self) -> None:
        prompt = self._test_entry.get().strip()
        if not prompt:
            return

        self._result_text.configure(state="normal")
        self._result_text.delete("1.0", "end")
        self._result_text.insert("1.0", "Querying NVIDIA NIM model...")
        self._result_text.configure(state="disabled")

        async def run():
            from openai import AsyncOpenAI

            from config.constants import LLM_BASE_URL, LLM_MODEL
            from config.settings import get_settings

            settings = get_settings()
            if not settings.llm_api_key:
                self.after(
                    0,
                    lambda: self._show_result(
                        "LLM_API_KEY is not set. Please update your environment variables."
                    ),
                )
                return

            try:
                client = AsyncOpenAI(
                    base_url=LLM_BASE_URL, api_key=settings.llm_api_key
                )
                response = await client.chat.completions.create(
                    model=LLM_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=256,
                    temperature=0.2,
                )
                res = response.choices[0].message.content or "No response from model."
                self.after(0, lambda: self._show_result(res))
            except Exception:
                self.after(0, lambda: self._show_result(f"Error querying model: {e}"))

        self._app.run_async(run())

    def _show_result(self, text: str) -> None:
        self._result_text.configure(state="normal")
        self._result_text.delete("1.0", "end")
        self._result_text.insert("1.0", text)
        self._result_text.configure(state="disabled")

    def refresh(self) -> None:
        async def _load():
            from config.constants import LLM_MODEL, VISION_MODEL
            from core.database import get_database

            db = get_database()

            # Query database for statistics
            stats = await db.get_ai_page_stats()
            decisions_count = stats["decisions_count"]
            memory_count = stats["memory_count"]
            avg_latency = f"{stats['avg_latency']} ms" if stats["avg_latency"] else "--"

            self.after(
                0,
                lambda: self._update_stats(
                    LLM_MODEL, VISION_MODEL, decisions_count, memory_count, avg_latency
                ),
            )

        self._app.run_async(_load())

    def _update_stats(self, model, vision, count, memory, latency):
        self._lbl_model.configure(text=model.split("/")[-1])
        self._lbl_vision.configure(text=vision.split("/")[-1])
        self._lbl_api.configure(text="NVIDIA NIM API")

        self._lbl_total_decisions.configure(text=str(count))
        self._lbl_cache_hits.configure(text=f"{memory} parsed fields")
        self._lbl_lat_avg.configure(text=latency)

    def on_show(self) -> None:
        self.refresh()
