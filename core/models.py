"""
Pydantic data models for all domain entities.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    NEW = "NEW"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    APPLIED = "APPLIED"
    SUBMITTED = "SUBMITTED"
    REDIRECTED = "REDIRECTED"
    EXTERNAL_REQUIRED = "EXTERNAL_REQUIRED"
    ERROR = "ERROR"


class Job(BaseModel):
    """Represents a discovered job listing."""

    id: int | None = None
    title: str = ""
    company: str = ""
    location: str = ""
    experience: str = ""
    salary: str = ""
    url: str = ""
    source: str = ""
    description: str = ""
    requirements: str = ""
    skills: str = ""
    posted_date: str = ""
    discovered_date: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: JobStatus = JobStatus.NEW

    class Config:
        use_enum_values = False


class SavedJob(BaseModel):
    """A job the user has bookmarked."""

    id: int | None = None
    job_id: int
    saved_date: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    job: Job | None = None


class AppliedJob(BaseModel):
    """A job the user has applied to."""

    id: int | None = None
    job_id: int
    applied_date: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    application_url: str = ""
    status: JobStatus = JobStatus.APPLIED
    notes: str = ""
    job: Job | None = None


class Notification(BaseModel):
    """In-app notification record."""

    id: int | None = None
    type: str = "info"  # info | warning | error | captcha
    message: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    read: bool = False


class SearchHistory(BaseModel):
    """Record of a past search run."""

    id: int | None = None
    keywords: str = ""
    locations: str = ""
    sources: str = ""
    results_count: int = 0
    searched_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ErrorLog(BaseModel):
    """Application error record."""

    id: int | None = None
    context: str = ""
    error_message: str = ""
    occurred_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class FormData(BaseModel):
    """Parsed contents of form.txt."""

    full_name: str = ""
    email: str = ""
    mobile: str = ""
    whatsapp: str = ""
    nationality: str = ""
    gender: str = ""
    dob: str = ""
    current_location: str = ""
    hometown: str = ""
    employment_status: str = ""
    notice_period: str = ""
    available_to_join: str = ""
    willing_relocate: str = ""
    willing_remote: str = ""
    linkedin: str = ""
    github: str = ""
    portfolio: str = ""
    highest_qual: str = ""
    branch: str = ""
    college: str = ""
    graduation_year: str = ""
    total_experience: str = ""
    internship: str = ""
    primary_skills: str = ""
    secondary_skills: str = ""
    preferred_roles: str = ""
    preferred_locations: str = ""
    expected_ctc: str = ""
    raw_content: str = ""
    custom_fields: dict[str, str] = Field(default_factory=dict)
