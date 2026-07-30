"""
Resume service — tracks resume path and validates file availability.
"""

from __future__ import annotations

from pathlib import Path

from core.logger import get_logger

logger = get_logger(__name__)


class ResumeService:
    def __init__(self, resume_path: str) -> None:
        self._path = Path(resume_path)

    @property
    def path(self) -> Path:
        return self._path

    @property
    def path_str(self) -> str:
        return str(self._path) if self._path else ""

    @property
    def exists(self) -> bool:
        if not self.path_str:
            return False
        return self._path.exists() and self._path.is_file()

    @property
    def filename(self) -> str:
        return self._path.name if self.path_str else ""

    @property
    def size_kb(self) -> float:
        if self.exists:
            return self._path.stat().st_size / 1024
        return 0.0

    def set_path(self, new_path: str) -> bool:
        """Update the resume path. Returns True if new file exists."""
        if not new_path:
            self._path = Path("")
            return True
        p = Path(new_path)
        if p.exists() and p.suffix.lower() == ".pdf":
            self._path = p
            logger.info("Resume path updated to: %s", p)
            return True
        logger.warning("Invalid resume path: %s", new_path)
        return False

    def validate(self) -> str | None:
        """Return error message if resume is not usable, else None."""
        if not self.path_str:
            return "No resume selected. Please upload a PDF."
        if not self.exists:
            return f"Resume not found: {self._path}"
        if self._path.suffix.lower() != ".pdf":
            return "Resume must be a PDF file"
        if self.size_kb < 1:
            return "Resume file appears to be empty"
        return None

    def get_status_text(self) -> str:
        if not self.path_str:
            return "[NOT SET] Please upload a resume"
        if self.exists:
            return f"[OK]  {self.filename}  ({self.size_kb:.1f} KB)"
        return f"[NOT FOUND]  {self._path}"


# ── Singleton ─────────────────────────────────────────────────────────────────

_resume_service: ResumeService | None = None


def get_resume_service() -> ResumeService:
    global _resume_service
    if _resume_service is None:
        from config.settings import get_settings

        _resume_service = ResumeService(get_settings().resume_path)
        try:
            from core.service_registry import ServiceRegistry

            ServiceRegistry.register("ResumeService", _resume_service)
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)
    return _resume_service
