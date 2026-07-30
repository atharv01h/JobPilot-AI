"""
Pydantic-based settings management.
Loads from .env, falls back to defaults, and can persist to settings.json.
"""

from __future__ import annotations

from core.logger import get_logger

logger = get_logger(__name__)

import json
import os
import threading
from collections.abc import Callable
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from config.constants import (
    EXPERIENCE_LEVELS,
    JOB_SOURCES,
    LLM_BASE_URL,
    LLM_MODEL,
    SEARCH_KEYWORDS,
    SEARCH_LOCATIONS,
)

_PROJECT_ROOT = Path(__file__).parent.parent
_SETTINGS_FILE = _PROJECT_ROOT / "settings.json"

# Lock for thread-safe settings persistence
_settings_lock = threading.Lock()


class AppSettings(BaseSettings):
    """Application settings — loaded from .env and overridable via GUI."""

    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM Configuration
    llm_provider: str = Field(
        default="nvidia",
        alias="LLM_PROVIDER",
        description="LLM provider (nvidia, openai, anthropic)",
    )
    llm_api_key: str = Field(
        default="",
        alias="LLM_API_KEY",
        description="API key for the selected LLM provider",
    )
    llm_model: str = Field(default=LLM_MODEL, alias="LLM_MODEL")
    llm_base_url: str = Field(default=LLM_BASE_URL, alias="LLM_BASE_URL")

    # File Paths
    resume_path: str = Field(
        default="",
        alias="RESUME_PATH",
    )
    profile_path: str = Field(
        default=str(_PROJECT_ROOT / "profile.json"),
        alias="PROFILE_PATH",
    )
    db_path: str = Field(
        default=str(_PROJECT_ROOT / "jobs.db"),
        alias="DB_PATH",
    )
    log_dir: str = Field(
        default=str(_PROJECT_ROOT / "logs"),
        alias="LOG_DIR",
    )

    # Search Configuration
    keywords: list[str] = Field(default_factory=lambda: SEARCH_KEYWORDS.copy())
    locations: list[str] = Field(default_factory=lambda: SEARCH_LOCATIONS.copy())
    experience_filters: list[str] = Field(
        default_factory=lambda: EXPERIENCE_LEVELS.copy()
    )
    job_sources: list[str] = Field(default_factory=lambda: JOB_SOURCES.copy())

    # Notifications
    desktop_notifications_enabled: bool = Field(
        default=True, alias="DESKTOP_NOTIFICATIONS_ENABLED"
    )

    # Scheduler
    scheduler_interval: str = Field(default="Manual", alias="SCHEDULER_INTERVAL")

    # Search Profile Preferences
    search_title: str = ""
    search_category: str = ""
    search_location: str = ""
    search_country: str = ""
    search_job_type: str = "All"
    search_experience: str = "All"
    search_work_mode: str = "All"
    search_salary: str = ""
    search_preferred_companies: str = ""
    search_blacklisted_companies: str = ""
    search_portals: list[str] = Field(
        default_factory=lambda: ["linkedin", "naukri", "indeed"]
    )
    auto_search_enabled: bool = False
    linkedin_easy_apply_mode: bool = False

    @field_validator("resume_path", "profile_path", mode="before")
    @classmethod
    def expand_path(cls, v: str) -> str:
        if not v:
            return ""
        return str(Path(v).expanduser().resolve())

    def save(self) -> None:
        """Persist current settings to settings.json (thread-safe)."""
        data = {
            "llm_provider": self.llm_provider,
            "llm_api_key": self.llm_api_key,
            "llm_model": self.llm_model,
            "llm_base_url": self.llm_base_url,
            "resume_path": self.resume_path,
            "profile_path": self.profile_path,
            "db_path": self.db_path,
            "log_dir": self.log_dir,
            "keywords": self.keywords,
            "locations": self.locations,
            "experience_filters": self.experience_filters,
            "job_sources": self.job_sources,
            "desktop_notifications_enabled": self.desktop_notifications_enabled,
            "scheduler_interval": self.scheduler_interval,
            "search_title": self.search_title,
            "search_category": self.search_category,
            "search_location": self.search_location,
            "search_country": self.search_country,
            "search_job_type": self.search_job_type,
            "search_experience": self.search_experience,
            "search_work_mode": self.search_work_mode,
            "search_salary": self.search_salary,
            "search_preferred_companies": self.search_preferred_companies,
            "search_blacklisted_companies": self.search_blacklisted_companies,
            "search_portals": self.search_portals,
            "auto_search_enabled": self.auto_search_enabled,
        }
        with _settings_lock, open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        _notify_settings_changed()

    @classmethod
    def load(cls) -> AppSettings:
        """Load settings: JSON overrides > .env > defaults."""
        if _SETTINGS_FILE.exists():
            with open(_SETTINGS_FILE, encoding="utf-8") as f:
                overrides = json.load(f)
            # Map JSON keys back to env aliases where needed
            env_map = {
                "llm_provider": "LLM_PROVIDER",
                "llm_api_key": "LLM_API_KEY",
                "llm_model": "LLM_MODEL",
                "llm_base_url": "LLM_BASE_URL",
                "resume_path": "RESUME_PATH",
                "profile_path": "PROFILE_PATH",
                "db_path": "DB_PATH",
                "log_dir": "LOG_DIR",
                "desktop_notifications_enabled": "DESKTOP_NOTIFICATIONS_ENABLED",
                "scheduler_interval": "SCHEDULER_INTERVAL",
            }
            for key, alias in env_map.items():
                if key in overrides:
                    os.environ[alias] = (
                        str(overrides[key])
                        if not isinstance(overrides[key], list)
                        else json.dumps(overrides[key])
                    )
            instance = cls()
            # Restore list fields directly
            for field in (
                "keywords",
                "locations",
                "experience_filters",
                "job_sources",
                "search_portals",
            ):
                if field in overrides:
                    setattr(instance, field, overrides[field])
            # Restore other search profile fields directly
            direct_fields = (
                "search_title",
                "search_category",
                "search_location",
                "search_country",
                "search_job_type",
                "search_experience",
                "search_work_mode",
                "search_salary",
                "search_preferred_companies",
                "search_blacklisted_companies",
                "auto_search_enabled",
            )
            for field in direct_fields:
                if field in overrides:
                    setattr(instance, field, overrides[field])
            return instance
        return cls()


# Singleton
_settings: AppSettings | None = None

# Settings change callbacks
_settings_changed_callbacks: list[Callable[[], None]] = []


def get_settings() -> AppSettings:
    global _settings
    if _settings is None:
        _settings = AppSettings.load()
    return _settings


def reload_settings() -> AppSettings:
    global _settings
    _settings = AppSettings.load()
    return _settings


def register_settings_changed_callback(callback: Callable[[], None]) -> None:
    """Register a callback to be called when settings are saved."""
    if callback not in _settings_changed_callbacks:
        _settings_changed_callbacks.append(callback)


def _notify_settings_changed() -> None:
    """Notify all registered callbacks that settings have changed."""
    for cb in _settings_changed_callbacks:
        try:
            cb()
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)
