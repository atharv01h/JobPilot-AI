"""
Profile Page — edit form.txt details interactively.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import customtkinter as ctk

from config.constants import COLORS, FONTS

if TYPE_CHECKING:
    from gui.app import App


class ProfilePage(ctk.CTkFrame):
    def __init__(self, master, app: App, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_primary"], **kwargs)
        self._app = app
        self._inputs: dict[str, ctk.CTkEntry] = {}
        self._custom_inputs: dict[str, ctk.CTkEntry] = {}
        self._custom_rows: list[ctk.CTkFrame] = []
        self._build()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=32, pady=(24, 0), sticky="ew")

        ctk.CTkLabel(
            header,
            text="Candidate Profile",
            font=FONTS["heading_xl"],
            text_color=COLORS["text_primary"],
        ).pack(side="left")

        ctk.CTkButton(
            header,
            text="💾  Save Profile Details",
            fg_color=COLORS["accent_green"],
            hover_color="#16A34A",
            font=FONTS["body_md"],
            height=38,
            corner_radius=10,
            command=self._save_profile,
        ).pack(side="right")

        ctk.CTkButton(
            header,
            text="📤 Upload TXT / PDF",
            fg_color=COLORS["accent_cyan"],
            hover_color="#0891b2",
            font=FONTS["body_md"],
            height=38,
            corner_radius=10,
            command=self._upload_txt,
        ).pack(side="right", padx=(0, 12))

        # Sub-header note
        ctk.CTkLabel(
            self,
            text="💡 Tip: You can edit 'sample_form.txt' in the project folder and upload it here to auto-fill your details!",
            font=FONTS["body_sm"],
            text_color=COLORS["text_secondary"],
            anchor="w",
        ).grid(row=1, column=0, padx=32, pady=(4, 0), sticky="w")

        # Scrollable form
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.grid(row=2, column=0, padx=32, pady=16, sticky="nsew")
        self.grid_rowconfigure(2, weight=1)
        scroll.grid_columnconfigure(0, weight=1)

        # ── Group 1: Personal Info ──
        grp_personal = self._create_group(scroll, "Personal Details")
        self._add_field(grp_personal, 0, "full_name", "Full Name:")
        self._add_field(grp_personal, 1, "email", "Email Address:")
        self._add_field(grp_personal, 2, "mobile", "Mobile Phone:")
        self._add_field(grp_personal, 3, "whatsapp", "WhatsApp Number:")
        self._add_field(grp_personal, 4, "gender", "Gender (Male/Female):")
        self._add_field(grp_personal, 5, "nationality", "Nationality:")

        # ── Group 2: Work & Location ──
        grp_work = self._create_group(scroll, "Experience & Job Preferences")
        self._add_field(grp_work, 0, "total_experience", "Total Experience (yrs):")
        self._add_field(grp_work, 1, "expected_ctc", "Expected CTC:")
        self._add_field(grp_work, 2, "notice_period", "Notice Period:")
        self._add_field(grp_work, 3, "current_location", "Current Location:")
        self._add_field(grp_work, 4, "preferred_locations", "Preferred Locations:")
        self._add_field(
            grp_work, 5, "willing_relocate", "Willing to Relocate (Yes/No):"
        )
        self._add_field(grp_work, 6, "willing_remote", "Willing to Remote (Yes/No):")

        # ── Group 3: Education & Skills ──
        grp_edu = self._create_group(scroll, "Education & Skills")
        self._add_field(grp_edu, 0, "highest_qual", "Highest Qualification:")
        self._add_field(grp_edu, 1, "branch", "Branch / Specialization:")
        self._add_field(grp_edu, 2, "college", "College / University:")
        self._add_field(grp_edu, 3, "graduation_year", "Graduation Year:")
        self._add_field(grp_edu, 4, "primary_skills", "Primary Skills (comma-sep):")
        self._add_field(grp_edu, 5, "secondary_skills", "Secondary Skills:")

        # ── Group 4: Social Links ──
        grp_social = self._create_group(scroll, "Online Portals")
        self._add_field(grp_social, 0, "linkedin", "LinkedIn URL:")
        self._add_field(grp_social, 1, "github", "GitHub URL:")
        self._add_field(grp_social, 2, "portfolio", "Portfolio Link:")

        # ── Group 5: Custom Fields ──
        self._grp_custom = self._create_group(scroll, "Custom Fields")
        ctk.CTkLabel(
            self._grp_custom,
            text="Add custom information you want the AI to know (e.g. Visa Status, Cover Letter).",
            font=FONTS["body_sm"],
            text_color=COLORS["text_muted"],
        ).grid(row=1, column=0, columnspan=2, padx=20, pady=(0, 12), sticky="w")
        
        self._custom_fields_container = ctk.CTkFrame(self._grp_custom, fg_color="transparent")
        self._custom_fields_container.grid(row=2, column=0, columnspan=2, sticky="nsew")
        self._custom_fields_container.grid_columnconfigure(0, weight=1)
        
        ctk.CTkButton(
            self._grp_custom,
            text="+ Add Custom Field",
            fg_color=COLORS["bg_hover"],
            hover_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            font=FONTS["body_sm"],
            command=self._add_new_custom_field_ui,
        ).grid(row=3, column=0, columnspan=2, padx=20, pady=12, sticky="w")

        self.refresh()

    def _create_group(self, parent: ctk.CTkFrame, name: str) -> ctk.CTkFrame:
        card = ctk.CTkFrame(
            parent,
            fg_color=COLORS["bg_card"],
            corner_radius=16,
            border_width=1,
            border_color=COLORS["border"],
        )
        card.pack(fill="x", pady=8)
        card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            card,
            text=name,
            font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"],
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, padx=20, pady=(14, 8), sticky="w")
        return card

    def _add_field(self, parent: ctk.CTkFrame, row: int, key: str, label: str) -> None:
        ctk.CTkLabel(
            parent,
            text=label,
            font=FONTS["body_sm"],
            text_color=COLORS["text_secondary"],
            anchor="w",
        ).grid(row=row + 1, column=0, padx=20, pady=6, sticky="w")

        entry = ctk.CTkEntry(parent, font=FONTS["body_sm"], height=32, corner_radius=6)
        entry.grid(row=row + 1, column=1, padx=20, pady=6, sticky="ew")
        self._inputs[key] = entry

    def _save_profile(self) -> None:
        from services.form_service import get_form_service

        fs = get_form_service()

        # Update data model directly
        for key, entry in self._inputs.items():
            val = entry.get().strip()
            if hasattr(fs.data, key):
                setattr(fs.data, key, val)

        # Save custom fields
        fs.data.custom_fields.clear()
        for key, entry in self._custom_inputs.items():
            val = entry.get().strip()
            if key and val:
                fs.data.custom_fields[key] = val

        try:
            # Save to JSON
            fs.save()
            from core.logger import get_logger
            logger = get_logger("ProfilePage")
            logger.info("Saved updated candidate profile details to profile.json")

            from gui.widgets.dialogs import MessageDialog

            MessageDialog(
                self.master,
                "Profile Saved",
                "Candidate details saved successfully!",
                icon="✅",
            )
        except Exception as e:
            from gui.widgets.dialogs import MessageDialog

            MessageDialog(
                self.master, "Error Saving", f"Failed to save profile: {e}", icon="❌"
            )

    def _add_new_custom_field_ui(self) -> None:
        dialog = ctk.CTkInputDialog(text="Enter Field Name (e.g., 'Visa Status'):", title="Custom Field")
        key = dialog.get_input()
        if not key or not key.strip() or key in self._custom_inputs:
            return
        self._render_custom_field(key.strip(), "")

    def _render_custom_field(self, key: str, value: str) -> None:
        row_frame = ctk.CTkFrame(self._custom_fields_container, fg_color="transparent")
        row_frame.pack(fill="x", padx=20, pady=4)
        row_frame.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(
            row_frame,
            text=f"{key}:",
            font=FONTS["body_sm"],
            text_color=COLORS["text_secondary"],
            width=150,
            anchor="w",
        ).grid(row=0, column=0, padx=(0, 10), sticky="w")
        
        entry = ctk.CTkEntry(row_frame, font=FONTS["body_sm"], height=32, corner_radius=6)
        entry.grid(row=0, column=1, sticky="ew")
        entry.insert(0, value)
        
        def _remove():
            row_frame.destroy()
            if key in self._custom_inputs:
                del self._custom_inputs[key]
                
        ctk.CTkButton(
            row_frame,
            text="✕",
            width=32,
            height=32,
            fg_color=COLORS["accent_red"],
            hover_color="#991b1b",
            command=_remove,
        ).grid(row=0, column=2, padx=(10, 0))
        
        self._custom_inputs[key] = entry
        self._custom_rows.append(row_frame)

    def _upload_txt(self) -> None:
        import tkinter.filedialog as fd
        path = fd.askopenfilename(
            title="Select Text or PDF File",
            filetypes=[("Text/PDF files", "*.txt *.pdf"), ("All files", "*.*")],
        )
        if not path:
            return
            
        async def _do_scan():
            import json

            from openai import AsyncOpenAI  # type: ignore

            from config.constants import LLM_BASE_URL, LLM_MODEL
            from config.settings import get_settings
            from core.logger import get_logger

            logger = get_logger("ProfilePage")

            try:
                # Read file
                if path.lower().endswith('.pdf'):
                    import fitz
                    doc = fitz.open(path)
                    raw_text = "\n".join(page.get_text("text") for page in doc)
                    doc.close()
                else:
                    with open(path, "r", encoding="utf-8") as f:
                        raw_text = f.read()
                        
                settings = get_settings()
                if not settings.llm_api_key:
                    raise ValueError("LLM API Key is required for auto-scanning.")
                
                client = AsyncOpenAI(base_url=LLM_BASE_URL, api_key=settings.llm_api_key)
                schema_desc = (
                    "Extract candidate profile data into JSON. Keys MUST be: full_name, email, mobile, "
                    "current_location, linkedin, github, portfolio, highest_qual, branch, college, "
                    "graduation_year, total_experience, primary_skills, expected_ctc. "
                    "Return ONLY valid JSON."
                )
                
                response = await client.chat.completions.create(
                    model=LLM_MODEL,
                    messages=[
                        {"role": "system", "content": "Return only valid JSON matching the requested keys."},
                        {"role": "user", "content": f"{schema_desc}\\n\\nText:\\n{raw_text[:6000]}"},
                    ],
                    max_tokens=2048,
                    temperature=0.1,
                )
                content = response.choices[0].message.content.strip()
                logger.info("Auto-scan LLM returned: %s", content)
                import re
                content = re.sub(r"```(?:json)?\n?", "", content).strip().rstrip("`")
                data = json.loads(content)
                logger.info("Parsed data keys: %s", list(data.keys()))
                
                # Apply data to UI on main thread
                def _apply():
                    for key, val in data.items():
                        if key in self._inputs and val:
                            self._inputs[key].delete(0, "end")
                            self._inputs[key].insert(0, str(val))
                    
                    from gui.widgets.dialogs import MessageDialog
                    MessageDialog(self.master, "Scan Complete", "Data extracted successfully! Review and save.", icon="✅")
                    
                self.after(0, _apply)
            except Exception as e:
                logger.error("Auto-scan failed: %s", e)
                def _err(err_msg=str(e)):
                    from gui.widgets.dialogs import MessageDialog
                    MessageDialog(self.master, "Error", f"Auto-scan failed:\n{err_msg}", icon="❌")
                self.after(0, _err)
                
        self._app.run_async(_do_scan())

    def refresh(self) -> None:
        from services.form_service import get_form_service

        fs = get_form_service()
        if fs.is_loaded and fs.data:
            profile_dict = fs.data.__dict__
            for key, entry in self._inputs.items():
                val = profile_dict.get(key, "")
                entry.delete(0, "end")
                entry.insert(0, str(val) if val is not None else "")
                
            # Clear existing custom UI
            for row in self._custom_rows:
                row.destroy()
            self._custom_rows.clear()
            self._custom_inputs.clear()
            
            # Load custom fields
            for k, v in getattr(fs.data, 'custom_fields', {}).items():
                self._render_custom_field(k, str(v))

    def on_show(self) -> None:
        self.refresh()
