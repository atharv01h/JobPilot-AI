"""
Auto-login service.
Stores site credentials and performs automatic login using Browser-Use
whenever a login page is detected — the user never needs to log in manually.

Credentials are stored in settings.json (local machine only).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from core.logger import get_logger

logger = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent
_CRED_FILE = _PROJECT_ROOT / "credentials.json"


@dataclass
class SiteCredential:
    """Login credentials for one job site."""

    email: str = ""
    password: str = ""


# Login page detection keywords per site
SITE_LOGIN_URLS: dict[str, list] = {
    "linkedin": ["linkedin.com/login", "linkedin.com/checkpoint", "linkedin.com/uas"],
    "naukri": ["naukri.com/login", "naukri.com/nLogin"],
    "indeed": ["indeed.com/account/login", "secure.indeed.com"],
    "glassdoor": ["glassdoor.co.in/profile/login", "glassdoor.com/profile/login"],
    "foundit": ["foundit.in/login", "foundit.in/mnjuser/dashboard"],
    "gmail": ["accounts.google.com", "mail.google.com"],
}


class AutoLoginService:
    """
    Stores credentials and builds Browser-Use login tasks.
    Called automatically when the browser hits a login page.
    """

    def __init__(self) -> None:
        self._creds: dict[str, SiteCredential] = {
            "linkedin": SiteCredential(),
            "naukri": SiteCredential(),
            "indeed": SiteCredential(),
            "glassdoor": SiteCredential(),
            "foundit": SiteCredential(),
            "gmail": SiteCredential(),
        }
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        if not _CRED_FILE.exists():
            return
        try:
            data = json.loads(_CRED_FILE.read_text(encoding="utf-8"))
            for site, vals in data.items():
                self._creds[site.lower()] = SiteCredential(
                    email=vals.get("email", ""),
                    password=vals.get("password", ""),
                )
            logger.info(
                "Credentials loaded for: %s",
                [s for s, c in self._creds.items() if c.email],
            )
        except Exception as exc:
            logger.warning("Failed to load credentials: %s", exc)

    def save(self) -> None:
        data = {
            site: {"email": c.email, "password": c.password}
            for site, c in self._creds.items()
        }
        _CRED_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.info("Credentials saved.")

    # ── Credential access ─────────────────────────────────────────────────────

    def set_credential(self, site: str, email: str, password: str) -> None:
        self._creds[site.lower()] = SiteCredential(email=email, password=password)

    def get_credential(self, site: str) -> SiteCredential:
        return self._creds.get(site.lower(), SiteCredential())

    def has_credential(self, site: str) -> bool:
        c = self._creds.get(site.lower(), SiteCredential())
        return bool(c.email and c.password)

    def all_sites(self) -> dict[str, SiteCredential]:
        return dict(self._creds)

    # ── Login detection ───────────────────────────────────────────────────────

    def detect_site_from_url(self, url: str) -> str | None:
        """Return site key if the URL is a known login page, else None."""
        url_lower = url.lower()
        for site, patterns in SITE_LOGIN_URLS.items():
            if any(p in url_lower for p in patterns):
                return site
        return None

    def detect_site_from_text(self, page_text: str, url: str = "") -> str | None:
        """Detect site from page content when URL is not specific enough."""
        combined = (url + " " + page_text).lower()
        for site in ("linkedin", "naukri", "indeed", "glassdoor", "foundit", "gmail"):
            if site in combined:
                return site
        return None

    # ── Login task builder ────────────────────────────────────────────────────

    def build_login_task(self, site: str, url: str) -> str | None:
        """
        Build a Browser-Use task string that logs in to the given site.
        Returns None if credentials are not configured.
        """
        cred = self.get_credential(site)
        if not cred.email or not cred.password:
            logger.warning(
                "No credentials configured for %s. "
                "Add them in Settings -> Login Credentials.",
                site,
            )
            return None

        site_instructions = {
            "linkedin": (
                "1. Find the email/phone field and type the email.\n"
                "2. Find the password field and type the password.\n"
                "3. Click the 'Sign in' button.\n"
                "4. Wait for the home page or feed to load.\n"
                "5. If a 2FA / OTP prompt appears, stop and report 'OTP_REQUIRED'.\n"
                "6. If login succeeds, report 'LOGIN_SUCCESS'."
            ),
            "naukri": (
                "1. Click 'Login' if a modal or button exists.\n"
                "2. Enter the email in the email field.\n"
                "3. Enter the password in the password field.\n"
                "4. Click 'Login' or 'Submit'.\n"
                "5. Wait for the dashboard to load.\n"
                "6. If OTP is required, stop and report 'OTP_REQUIRED'.\n"
                "7. If login succeeds, report 'LOGIN_SUCCESS'."
            ),
            "indeed": (
                "1. Enter the email address.\n"
                "2. Click Continue or Next.\n"
                "3. Enter the password.\n"
                "4. Click 'Sign in'.\n"
                "5. Wait for the dashboard.\n"
                "6. If OTP is required, stop and report 'OTP_REQUIRED'.\n"
                "7. If login succeeds, report 'LOGIN_SUCCESS'."
            ),
            "glassdoor": (
                "1. Find the email field and enter the email.\n"
                "2. Find the password field and enter the password.\n"
                "3. Click 'Sign In'.\n"
                "4. Wait for the homepage.\n"
                "5. If OTP is required, stop and report 'OTP_REQUIRED'.\n"
                "6. If login succeeds, report 'LOGIN_SUCCESS'."
            ),
            "foundit": (
                "1. Find the email or username field and enter the email.\n"
                "2. Find the password field and enter the password.\n"
                "3. Click 'Login' or 'Sign In'.\n"
                "4. Wait for the dashboard to load.\n"
                "5. If OTP is required, stop and report 'OTP_REQUIRED'.\n"
                "6. If login succeeds, report 'LOGIN_SUCCESS'."
            ),
            "gmail": (
                "1. Find the email or identifier field and enter the email.\n"
                "2. Click 'Next' or 'Continue'.\n"
                "3. Find the password field and enter the password.\n"
                "4. Click 'Next' or 'Sign in'.\n"
                "5. Wait for the Inbox or dashboard to load.\n"
                "6. If OTP / 2FA / verification is required, stop and report 'OTP_REQUIRED'.\n"
                "7. If login succeeds, report 'LOGIN_SUCCESS'."
            ),
        }

        instructions = site_instructions.get(
            site,
            (
                "1. Find email and password fields and fill them.\n"
                "2. Submit the login form.\n"
                "3. Report 'LOGIN_SUCCESS' on success or 'OTP_REQUIRED' if needed."
            ),
        )

        return f"""
Navigate to: {url}

You need to log in to {site.capitalize()} using these credentials:
Email:    {cred.email}
Password: {cred.password}

Steps:
{instructions}

IMPORTANT:
- Do NOT use vision mode
- Do NOT store or share the credentials anywhere
- If CAPTCHA appears, stop and report 'CAPTCHA_DETECTED'
- If already logged in, just report 'LOGIN_SUCCESS'
"""


# ── Singleton ─────────────────────────────────────────────────────────────────

_auto_login: AutoLoginService | None = None


def get_auto_login_service() -> AutoLoginService:
    global _auto_login
    if _auto_login is None:
        _auto_login = AutoLoginService()
    return _auto_login
