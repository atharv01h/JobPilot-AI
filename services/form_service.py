"""
Loads and saves candidate profile details as structured JSON (profile.json).
Provides field lookup for browser automation form filling.
"""

from __future__ import annotations

from pathlib import Path

from core.logger import get_logger
from core.models import FormData

logger = get_logger(__name__)


class FormService:
    """Loads and saves candidate profile details as structured JSON (profile.json)."""

    def __init__(self, profile_path: str) -> None:
        self.profile_path = Path(profile_path)
        self._data: FormData = FormData()
        self._loaded = False

    def load(self) -> bool:
        """Load and parse profile.json. Returns True on success."""
        if not self.profile_path.exists():
            logger.warning(
                "profile.json not found at %s. Using default empty form.",
                self.profile_path,
            )
            self._data = FormData()
            self._loaded = True
            return True

        try:
            raw = self.profile_path.read_text(encoding="utf-8")
            self._data = FormData.model_validate_json(raw)
            self._loaded = True
            logger.info("Profile data loaded from %s", self.profile_path)
            return True
        except Exception as exc:
            logger.error("Failed to load profile.json: %s", exc)
            self._data = FormData()  # Fallback
            return False

    def save(self) -> bool:
        """Save the current FormData model to profile.json."""
        try:
            json_str = self._data.model_dump_json(indent=2)
            self.profile_path.write_text(json_str, encoding="utf-8")
            logger.info("Profile saved to %s", self.profile_path)
            return True
        except Exception as exc:
            logger.error("Failed to save profile.json: %s", exc)
            return False

    @property
    def data(self) -> FormData:
        return self._data

    @property
    def is_loaded(self) -> bool:
        return self._loaded
        
    @property
    def raw(self) -> str:
        """Return raw JSON string for compatibility with old code."""
        return self._data.model_dump_json(indent=2)

    def get_field(self, field_name: str) -> str:
        """
        Fuzzy field lookup. Tries exact key, then partial match.
        Used by form filler to match HTML field labels -> user data.
        """
        key = field_name.lower().strip().replace(" ", "_").replace("-", "_")
        d = self._data.model_dump()

        # 1. Exact match
        if key in d:
            val = d[key]
            return str(val) if val is not None else ""

        # 2. Exact match in custom fields
        custom = self._data.custom_fields
        if key in custom:
            return str(custom[key])
        
        # 3. Partial match in custom fields
        for k, v in custom.items():
            if len(k) >= 3 and (key in k or k in key):
                return str(v)

        # 4. Partial match in standard fields
        for k, v in d.items():
            if k == "custom_fields":
                continue
            if len(k) >= 3 and (key in k or k in key):
                return str(v) if v is not None else ""
        return ""

    def as_dict(self) -> dict[str, str]:
        """Return all parsed key-value pairs as strings."""
        return {k: (str(v) if v is not None else "") for k, v in self._data.model_dump().items()}

    def get_form_summary(self) -> str:
        """Return a formatted summary for LLM context."""
        d = self._data
        return f"""
Name: {d.full_name}
Email: {d.email}
Phone: {d.mobile}
Location: {d.current_location}
Experience: {d.total_experience}
Status: {d.employment_status}
Primary Skills: {d.primary_skills}
Secondary Skills: {d.secondary_skills}
Preferred Roles: {d.preferred_roles}
Notice Period: {d.notice_period}
Expected CTC: {d.expected_ctc}
LinkedIn: {d.linkedin}
GitHub: {d.github}
Education: {d.highest_qual} in {d.branch} from {d.college}
Custom Fields: {", ".join([f"{k}: {v}" for k, v in d.custom_fields.items()])}
""".strip()


# ── Singleton ─────────────────────────────────────────────────────────────────

_form_service: FormService | None = None


def get_form_service() -> FormService:
    global _form_service
    if _form_service is None:
        from config.settings import get_settings

        settings = get_settings()
        _form_service = FormService(settings.profile_path)
        _form_service.load()
        try:
            from core.service_registry import ServiceRegistry

            ServiceRegistry.register("FormService", _form_service)
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)
    return _form_service
