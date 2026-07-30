"""
Diagnostics Page — runs startup self-test diagnostics and checks missing features/strategy statuses.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import customtkinter as ctk

from config.constants import COLORS, FONTS

if TYPE_CHECKING:
    from gui.app import App


class DiagnosticsPage(ctk.CTkFrame):
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
            text="Diagnostics & System Health",
            font=FONTS["heading_xl"],
            text_color=COLORS["text_primary"],
        ).pack(side="left")

        ctk.CTkButton(
            header,
            text="🛠  Run System Self-Test",
            fg_color=COLORS["accent_primary"],
            hover_color=COLORS["accent_secondary"],
            font=FONTS["body_md"],
            height=38,
            corner_radius=10,
            command=self._run_diagnostics,
        ).pack(side="right")

        # Scrollable area
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.grid(row=1, column=0, padx=32, pady=12, sticky="nsew")
        self.grid_rowconfigure(1, weight=1)
        scroll.grid_columnconfigure(0, weight=1)

        # Missing Features Checkbox Checklist Card
        card_features = ctk.CTkFrame(
            scroll,
            fg_color=COLORS["bg_card"],
            corner_radius=16,
            border_width=1,
            border_color=COLORS["border"],
        )
        card_features.pack(fill="x", pady=8)
        card_features.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            card_features,
            text="Missing Strategy / Feature Statuses",
            font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"],
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, padx=20, pady=(16, 8), sticky="w")

        self._lbl_winui = self._create_row(
            card_features, 1, "Windows Desktop UI Strategy (pywinauto):"
        )
        self._lbl_pya = self._create_row(
            card_features, 2, "Mouse/Keyboard Automation (pyautogui):"
        )
        self._lbl_opencv = self._create_row(card_features, 3, "CV2 Screen Matching:")
        self._lbl_easyocr = self._create_row(
            card_features, 4, "Local EasyOCR Vision Support:"
        )

        # Vision Fallback Pipeline Status
        card_vision = ctk.CTkFrame(
            scroll,
            fg_color=COLORS["bg_card"],
            corner_radius=16,
            border_width=1,
            border_color=COLORS["border"],
        )
        card_vision.pack(fill="x", pady=8)
        card_vision.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            card_vision,
            text="Vision Failover Pipeline Availability",
            font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"],
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, padx=20, pady=(16, 8), sticky="w")

        self._lbl_nim = self._create_row(
            card_vision, 1, "1. NVIDIA NIM Multimodal (Default):"
        )
        self._lbl_gem = self._create_row(
            card_vision, 2, "2. Gemini Vision API (Failover):"
        )
        self._lbl_oai = self._create_row(
            card_vision, 3, "3. OpenAI Vision API (Failover):"
        )
        self._lbl_ocr = self._create_row(
            card_vision, 4, "4. Local OCR Parser (Fallback):"
        )
        self._lbl_dom = self._create_row(
            card_vision, 5, "5. DOM OCR Parser (Fallback):"
        )

        # Diagnostics Output Log Card
        card_log = ctk.CTkFrame(
            scroll,
            fg_color=COLORS["bg_card"],
            corner_radius=16,
            border_width=1,
            border_color=COLORS["border"],
        )
        card_log.pack(fill="both", expand=True, pady=8)

        ctk.CTkLabel(
            card_log,
            text="Self-Test Diagnostics Report Logs",
            font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"],
            anchor="w",
        ).pack(padx=20, pady=(16, 8), anchor="w")

        self._report_box = ctk.CTkTextbox(
            card_log,
            font=FONTS["mono"],
            height=200,
            fg_color=COLORS["bg_secondary"],
            text_color=COLORS["text_primary"],
            wrap="word",
        )
        self._report_box.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self._report_box.insert(
            "1.0", "Click 'Run System Self-Test' above to execute tests..."
        )
        self._report_box.configure(state="disabled")

        self.refresh()

    def _create_row(self, parent: ctk.CTkFrame, row: int, label: str) -> ctk.CTkLabel:
        lbl = ctk.CTkLabel(
            parent,
            text=label,
            font=FONTS["body_sm"],
            text_color=COLORS["text_secondary"],
            anchor="w",
        )
        lbl.grid(row=row, column=0, padx=20, pady=6, sticky="w")

        val_lbl = ctk.CTkLabel(
            parent,
            text="--",
            font=FONTS["body_sm"],
            text_color=COLORS["text_primary"],
            anchor="e",
        )
        val_lbl.grid(row=row, column=1, padx=20, pady=6, sticky="e")
        return val_lbl

    def _run_diagnostics(self) -> None:
        self._report_box.configure(state="normal")
        self._report_box.delete("1.0", "end")
        self._report_box.insert(
            "1.0", "Running system-wide self-test suite, please wait...\n"
        )
        self._report_box.configure(state="disabled")

        async def run():
            # Intercept stdout prints from ServiceRegistry self test
            import io
            import sys

            from core.service_registry import ServiceRegistry

            old_stdout = sys.stdout
            new_stdout = io.StringIO()
            sys.stdout = new_stdout

            try:
                await ServiceRegistry.perform_self_test()
                sys.stdout = old_stdout
                report = new_stdout.getvalue()
                self.after(0, lambda: self._show_report(report))
            except Exception:
                sys.stdout = old_stdout
                self.after(0, lambda: self._show_report(f"Self-test crashed: {e}"))

        self._app.run_async(run())

    def _show_report(self, text: str) -> None:
        self._report_box.configure(state="normal")
        self._report_box.delete("1.0", "end")
        self._report_box.insert("1.0", text)
        self._report_box.configure(state="disabled")
        self.refresh()

    def refresh(self) -> None:
        # Load missing features from dependency guard
        from automation.dependency_guard import DISABLED_STRATEGIES

        def _get_status(flag):
            return (
                "DISABLED (Missing Package)"
                if DISABLED_STRATEGIES.get(flag, False)
                else "ACTIVE (Enabled)"
            )

        def _get_color(flag):
            return (
                COLORS["accent_red"]
                if DISABLED_STRATEGIES.get(flag, False)
                else COLORS["accent_green"]
            )

        self._lbl_winui.configure(
            text=_get_status("WINUI_DISABLED"), text_color=_get_color("WINUI_DISABLED")
        )
        self._lbl_pya.configure(
            text=_get_status("PYAUTOGUI_DISABLED"),
            text_color=_get_color("PYAUTOGUI_DISABLED"),
        )
        self._lbl_opencv.configure(
            text=_get_status("OPENCV_DISABLED"),
            text_color=_get_color("OPENCV_DISABLED"),
        )
        self._lbl_easyocr.configure(
            text=_get_status("EASYOCR_DISABLED"),
            text_color=_get_color("EASYOCR_DISABLED"),
        )

        # Load Vision Fallbacks
        from automation.vision_engine import get_vision_engine

        ve = get_vision_engine()
        v_status = ve.get_vision_status()

        def _v_color(status):
            return (
                COLORS["accent_green"]
                if status == "Available"
                else COLORS["accent_red"]
            )

        self._lbl_nim.configure(
            text=v_status.get("NVIDIA NIM Vision", "--"),
            text_color=_v_color(v_status.get("NVIDIA NIM Vision")),
        )
        self._lbl_gem.configure(
            text=v_status.get("Gemini Vision API", "--"),
            text_color=_v_color(v_status.get("Gemini Vision API")),
        )
        self._lbl_oai.configure(
            text=v_status.get("OpenAI Vision API", "--"),
            text_color=_v_color(v_status.get("OpenAI Vision API")),
        )

        local_ocr = "Not Installed"
        if (
            v_status.get("EasyOCR (Local)") == "Available"
            or v_status.get("Tesseract (Local)") == "Available"
            or v_status.get("PaddleOCR (Local)") == "Available"
        ):
            local_ocr = "Available"
        self._lbl_ocr.configure(text=local_ocr, text_color=_v_color(local_ocr))
        self._lbl_dom.configure(
            text=v_status.get("DOM OCR (Browser)", "--"),
            text_color=_v_color(v_status.get("DOM OCR (Browser)")),
        )

    def on_show(self) -> None:
        self.refresh()
