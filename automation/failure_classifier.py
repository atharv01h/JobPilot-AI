"""
failure_classifier.py — Canonical failure reason registry.

All skip/failure paths in the system must use these reason strings.
Stored in database, audit logs, and console output for every failed application.
"""

from __future__ import annotations

from enum import Enum


class FailureReason(str, Enum):
    """
    Canonical failure classification for every skipped or failed job application.

    These are the ONLY valid failure reasons accepted throughout the system.
    """

    # Upload-related
    UPLOAD_FAILED = "UPLOAD_FAILED"

    # Authentication / account walls
    ACCOUNT_REQUIRED = "ACCOUNT_REQUIRED"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"

    # Verification barriers
    CAPTCHA_BLOCKED = "CAPTCHA_BLOCKED"
    OTP_REQUIRED = "OTP_REQUIRED"
    EMAIL_VERIFICATION_REQUIRED = "EMAIL_VERIFICATION_REQUIRED"

    # Site-level blockers
    UNSUPPORTED_SITE = "UNSUPPORTED_SITE"
    APPLICATION_CLOSED = "APPLICATION_CLOSED"

    # Automation failures
    FORM_LOOP = "FORM_LOOP"
    AI_FAILURE = "AI_FAILURE"
    NETWORK_ERROR = "NETWORK_ERROR"
    TIMEOUT = "TIMEOUT"

    # Catch-all
    UNKNOWN = "UNKNOWN"


# Reasons that indicate the job is permanently unprocessable (skip immediately, never retry)
PERMANENT_FAILURES = {
    FailureReason.ACCOUNT_REQUIRED,
    FailureReason.LOGIN_REQUIRED,
    FailureReason.CAPTCHA_BLOCKED,
    FailureReason.OTP_REQUIRED,
    FailureReason.EMAIL_VERIFICATION_REQUIRED,
    FailureReason.UNSUPPORTED_SITE,
    FailureReason.APPLICATION_CLOSED,
}

# Reasons that may be transient and could theoretically be retried (future use)
TRANSIENT_FAILURES = {
    FailureReason.UPLOAD_FAILED,
    FailureReason.NETWORK_ERROR,
    FailureReason.TIMEOUT,
    FailureReason.FORM_LOOP,
    FailureReason.AI_FAILURE,
    FailureReason.UNKNOWN,
}

# Map legacy string statuses to canonical FailureReason
_LEGACY_MAP: dict[str, FailureReason] = {
    "APPLICATION_FAILED": FailureReason.UNKNOWN,
    "REDIRECTED_TO_COMPANY": FailureReason.ACCOUNT_REQUIRED,
    "EXTERNAL_APPLICATION_REQUIRED": FailureReason.UNSUPPORTED_SITE,
    "APPLICATION_SKIPPED": FailureReason.UNKNOWN,
}


def classify(status: str) -> FailureReason:
    """
    Convert any status string (legacy or new) to a canonical FailureReason.
    Falls back to UNKNOWN on unrecognized input.
    """
    # Try direct enum lookup
    try:
        return FailureReason(status)
    except ValueError:
        pass
    # Try legacy map
    mapped = _LEGACY_MAP.get(status)
    if mapped:
        return mapped
    return FailureReason.UNKNOWN


def is_permanent(reason: FailureReason) -> bool:
    """Return True if this failure means we should never retry this job."""
    return reason in PERMANENT_FAILURES


def should_skip_immediately(reason_str: str) -> bool:
    """
    Convenience: return True if a raw reason string maps to a permanent failure.
    Used at queue level to decide whether to log a skip without retry.
    """
    return is_permanent(classify(reason_str))
