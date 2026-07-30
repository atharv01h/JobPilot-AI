"""
site_upload_profiles.py — Per-site resume upload intelligence.

Each SiteUploadProfile describes where and how to trigger the resume upload
on a specific job website. This drives the UploadManager strategy selection
and provides site-specific trigger selectors.

Adding a new site: add an entry to SITE_PROFILES with the site's known
file input selectors, upload trigger selectors, and known iframe patterns.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SiteUploadProfile:
    """
    Describes resume upload behavior for a specific job site.

    Attributes:
        site:                     Canonical site name (lowercase)
        file_input_selectors:     CSS selectors for input[type=file], most-specific first
        trigger_selectors:        CSS selectors for the button/link that opens upload
        iframe_selectors:         iframe selectors wrapping the form (if any)
        verify_selectors:         Selectors that appear after successful upload
        success_keywords:         Strings in body text confirming upload
        preferred_strategy:       Strategy name to try first for this site
        notes:                    Developer notes about upload quirks
    """

    site: str
    file_input_selectors: list[str] = field(default_factory=list)
    trigger_selectors: list[str] = field(default_factory=list)
    iframe_selectors: list[str] = field(default_factory=list)
    verify_selectors: list[str] = field(default_factory=list)
    success_keywords: list[str] = field(default_factory=list)
    preferred_strategy: str = "DIRECT"
    notes: str = ""


# ── Site Profiles ─────────────────────────────────────────────────────────────

SITE_PROFILES: dict[str, SiteUploadProfile] = {
    "linkedin": SiteUploadProfile(
        site="linkedin",
        file_input_selectors=[
            "input.jobs-document-upload__input",
            "input[data-test-resume-upload-input]",
            "input[type='file'][accept*='pdf']",
            "input[type='file']",
        ],
        trigger_selectors=[
            "button.jobs-document-upload__upload-button",
            "button:has-text('Upload resume')",
            "button:has-text('Choose resume')",
            "label.jobs-document-upload__upload-button",
        ],
        iframe_selectors=[],
        verify_selectors=[
            "[class*='document-upload__filename']",
            "[class*='resume-name']",
            ".jobs-document-upload__filename",
        ],
        success_keywords=["resume", "cv", ".pdf", "uploaded"],
        preferred_strategy="DIRECT",
        notes=(
            "LinkedIn uses a hidden file input with class 'jobs-document-upload__input'. "
            "set_input_files() works directly without clicking the label. "
            "The form is in a modal div, not an iframe."
        ),
    ),
    "naukri": SiteUploadProfile(
        site="naukri",
        file_input_selectors=[
            "input#attachCV",
            "input[name='attachCV']",
            "input[type='file'][accept*='.pdf']",
            "input[type='file'][accept*='.doc']",
            "input[type='file']",
        ],
        trigger_selectors=[
            "label[for='attachCV']",
            "button:has-text('Upload resume')",
            "button:has-text('Replace resume')",
            "#fileUploadBtn",
            ".upload-btn-wrapper button",
        ],
        iframe_selectors=[],
        verify_selectors=[
            ".file-name-text",
            ".uploaded-file-name",
            "#resumeFileName",
        ],
        success_keywords=["resume uploaded", "file uploaded", ".pdf", ".doc"],
        preferred_strategy="DIRECT",
        notes=(
            "Naukri uses input#attachCV which may be hidden behind a styled label. "
            "set_input_files() on the hidden input works without revealing it."
        ),
    ),
    "indeed": SiteUploadProfile(
        site="indeed",
        file_input_selectors=[
            "input[type='file']",
            "input[accept*='pdf']",
        ],
        trigger_selectors=[
            "button:has-text('Upload resume')",
            "button:has-text('Choose file')",
            "label:has-text('Upload')",
            "[data-testid='ResumePicker-file-input']",
        ],
        iframe_selectors=[
            "iframe[src*='indeedapply']",
            "iframe[title*='Indeed Apply']",
            "iframe[src*='apply']",
        ],
        verify_selectors=[
            "[data-testid='ResumePreview']",
            ".ia-ResumeConfirmation",
            "[class*='resume-preview']",
        ],
        success_keywords=["resume", ".pdf", "uploaded", "confirmed"],
        preferred_strategy="FILE_CHOOSER",
        notes=(
            "Indeed uses an iframe for its apply flow. The file input is inside "
            "'iframe[src*=indeedapply]'. Use frame_locator() to scope actions. "
            "FileChooser strategy works when direct input fails."
        ),
    ),
    "foundit": SiteUploadProfile(
        site="foundit",
        file_input_selectors=[
            "input[type='file']",
            "input[accept*='pdf']",
            "input[accept*='doc']",
        ],
        trigger_selectors=[
            "button:has-text('Upload resume')",
            "button:has-text('Upload CV')",
            "button:has-text('Attach resume')",
            ".resumeUploadBtn",
        ],
        iframe_selectors=[],
        verify_selectors=[
            ".resume-file-name",
            ".uploaded-resume-name",
        ],
        success_keywords=["uploaded", ".pdf", "attached"],
        preferred_strategy="DIRECT",
        notes="Foundit (formerly Monster India) — standard file input pattern.",
    ),
    "wellfound": SiteUploadProfile(
        site="wellfound",
        file_input_selectors=[
            "input[type='file'][accept*='pdf']",
            "input[type='file']",
        ],
        trigger_selectors=[
            "button:has-text('Upload resume')",
            "button:has-text('Attach')",
            "label:has-text('Upload')",
        ],
        iframe_selectors=[],
        verify_selectors=[
            ".resume-filename",
            "[data-test='resume-name']",
        ],
        success_keywords=["resume", ".pdf", "uploaded"],
        preferred_strategy="FILE_CHOOSER",
        notes=(
            "Wellfound (AngelList) uses a styled button that triggers FileChooser. "
            "File input may not be directly accessible in DOM — use FileChooser strategy."
        ),
    ),
    "instahyre": SiteUploadProfile(
        site="instahyre",
        file_input_selectors=[
            "input[type='file']",
        ],
        trigger_selectors=[
            "button:has-text('Upload Resume')",
            "button:has-text('Attach')",
        ],
        iframe_selectors=[],
        verify_selectors=[],
        success_keywords=["resume", "uploaded", ".pdf"],
        preferred_strategy="DIRECT",
        notes="Instahyre — standard direct input. May require scrolling to reveal form.",
    ),
    "glassdoor": SiteUploadProfile(
        site="glassdoor",
        file_input_selectors=[
            "input[type='file']",
            "input[accept*='pdf']",
        ],
        trigger_selectors=[
            "button:has-text('Upload Resume')",
            "button:has-text('Upload')",
            "label[for*='resume']",
        ],
        iframe_selectors=[],
        verify_selectors=[
            ".resume-filename",
            "[data-test='resume-file-name']",
        ],
        success_keywords=["resume", ".pdf", "uploaded"],
        preferred_strategy="DIRECT",
        notes="Glassdoor — file input may be hidden inside a styled upload area.",
    ),
}


def get_profile(site: str) -> SiteUploadProfile | None:
    """Return the upload profile for a given site name, or None if not found."""
    return SITE_PROFILES.get(site.lower())


def get_all_sites() -> list[str]:
    """Return all supported site names."""
    return list(SITE_PROFILES.keys())
