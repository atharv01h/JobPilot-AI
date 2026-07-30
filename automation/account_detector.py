"""
account_detector.py — Immediate login/signup wall + smart skip detector.

Scans any company ATS page for authentication walls and instant-skip conditions
BEFORE any form filling or button clicking begins.

Design:
  - Zero retries on positive detection.
  - Returns a FailureReason string for logging + DB storage.
  - Never blocks the queue — caller closes tab and moves on.
"""

from __future__ import annotations

import re

from playwright.async_api import Page

from core.logger import get_logger

logger = get_logger(__name__)


# ── Instant-skip patterns ─────────────────────────────────────────────────────
# Each entry: (page_text_keyword, failure_reason)
# Matched case-insensitively against full page body text.

_ACCOUNT_REQUIRED_PATTERNS: list[tuple[str, str]] = [
    # Login / Sign-in walls
    ("sign in to apply", "ACCOUNT_REQUIRED"),
    ("log in to apply", "ACCOUNT_REQUIRED"),
    ("login to apply", "ACCOUNT_REQUIRED"),
    ("sign in to continue", "ACCOUNT_REQUIRED"),
    ("log in to continue", "ACCOUNT_REQUIRED"),
    ("please sign in", "LOGIN_REQUIRED"),
    ("please log in", "LOGIN_REQUIRED"),
    ("you must be logged in", "LOGIN_REQUIRED"),
    ("you must sign in", "LOGIN_REQUIRED"),
    # Registration / Account creation walls
    ("create an account to apply", "ACCOUNT_REQUIRED"),
    ("create account to continue", "ACCOUNT_REQUIRED"),
    ("create a candidate account", "ACCOUNT_REQUIRED"),
    ("create applicant account", "ACCOUNT_REQUIRED"),
    ("create your candidate profile", "ACCOUNT_REQUIRED"),
    ("register to apply", "ACCOUNT_REQUIRED"),
    ("join to apply", "ACCOUNT_REQUIRED"),
    ("new user? register", "ACCOUNT_REQUIRED"),
    ("create a profile to apply", "ACCOUNT_REQUIRED"),
    # OTP / Phone verification
    ("verify your phone", "OTP_REQUIRED"),
    ("sms verification", "OTP_REQUIRED"),
    ("enter the code sent to", "OTP_REQUIRED"),
    ("one-time password", "OTP_REQUIRED"),
    ("otp required", "OTP_REQUIRED"),
    # Email verification gate
    ("verify your email to continue", "EMAIL_VERIFICATION_REQUIRED"),
    ("confirm your email address", "EMAIL_VERIFICATION_REQUIRED"),
    ("email verification required", "EMAIL_VERIFICATION_REQUIRED"),
]

_INSTANT_SKIP_PATTERNS: list[tuple[str, str]] = [
    # Access restriction
    ("employee referral required", "UNSUPPORTED_SITE"),
    ("internal employees only", "UNSUPPORTED_SITE"),
    ("internal applicants only", "UNSUPPORTED_SITE"),
    ("invitation required", "UNSUPPORTED_SITE"),
    ("referred candidates only", "UNSUPPORTED_SITE"),
    # Application status
    ("this position is no longer available", "APPLICATION_CLOSED"),
    ("this job is no longer available", "APPLICATION_CLOSED"),
    ("position has been filled", "APPLICATION_CLOSED"),
    ("job posting has expired", "APPLICATION_CLOSED"),
    ("application period has closed", "APPLICATION_CLOSED"),
    ("applications are closed", "APPLICATION_CLOSED"),
    ("this role is closed", "APPLICATION_CLOSED"),
    # Payments / fees
    ("payment required", "UNSUPPORTED_SITE"),
    ("application fee", "UNSUPPORTED_SITE"),
    # Government ID / biometric
    ("government-issued id required", "UNSUPPORTED_SITE"),
    ("government id mandatory", "UNSUPPORTED_SITE"),
    # CAPTCHA / bot challenge (non-automated)
    ("please complete the captcha", "CAPTCHA_BLOCKED"),
    ("prove you are not a robot", "CAPTCHA_BLOCKED"),
    # Unsolvable SMS / phone verification
    ("enter your mobile number to receive a code", "OTP_REQUIRED"),
]

# URL patterns that indicate authentication wall
_AUTH_URL_PATTERNS = [
    r"/login",
    r"/signin",
    r"/sign-in",
    r"/sign_in",
    r"/auth",
    r"/sso",
    r"/register",
    r"/signup",
    r"/sign-up",
    r"/create-account",
    r"/create_account",
    r"/account/new",
    r"/users/sign_in",
    r"/session/new",
]

# DOM selectors that confirm an auth wall (any visible = wall detected)
_AUTH_DOM_SELECTORS = [
    "form[action*='login']",
    "form[action*='signin']",
    "form[action*='sign_in']",
    "form[action*='register']",
    "form[action*='signup']",
    "input[name='password'][type='password']",
    "input[id*='password']",
    "button:has-text('Sign In')",
    "button:has-text('Log In')",
    "button:has-text('Create Account')",
    "button:has-text('Register')",
    "a:has-text('Create Account')",
    "[data-test*='login']",
    "[data-testid*='login']",
    "[class*='login-form']",
    "[class*='signup-form']",
    "[class*='auth-form']",
]


class AccountDetector:
    """
    Detects authentication walls and instant-skip conditions on company ATS pages.

    Call detect(page) immediately after navigating to any external company site.
    Returns a failure reason string if the page should be skipped, or None to proceed.
    """

    async def detect(self, page: Page) -> str | None:
        """
        Scan the current page for login/signup walls and skip conditions.

        Returns:
            str — failure reason (e.g. "ACCOUNT_REQUIRED") if skip is required
            None — page looks clean, proceed with application
        """
        url = page.url.lower()
        logger.info("AccountDetector: scanning page: %s", url)

        # 1. Fast URL check
        reason = self._check_url(url)
        if reason:
            logger.warning("AccountDetector: URL pattern match → %s (%s)", reason, url)
            return reason

        # 2. Page text check (covers most cases efficiently)
        try:
            body_text = await page.inner_text("body", timeout=4000)
            body_lower = body_text.lower()
        except Exception as exc:
            logger.debug("AccountDetector: could not read body text: %s", exc)
            body_lower = ""

        if body_lower:
            reason = self._check_text(body_lower)
            if reason:
                logger.warning("AccountDetector: text pattern match → %s", reason)
                return reason

        # 3. DOM selector check (catches hidden/dynamic auth forms)
        reason = await self._check_dom(page)
        if reason:
            logger.warning("AccountDetector: DOM selector match → %s", reason)
            return reason

        logger.info("AccountDetector: no wall detected — page is clear.")
        return None

    def _check_url(self, url_lower: str) -> str | None:
        """Check URL path for authentication patterns."""
        for pattern in _AUTH_URL_PATTERNS:
            if re.search(pattern, url_lower):
                return "LOGIN_REQUIRED"
        return None

    def _check_text(self, body_lower: str) -> str | None:
        """Check page body text for skip conditions."""
        # Account required / auth walls (highest priority)
        for keyword, reason in _ACCOUNT_REQUIRED_PATTERNS:
            if keyword in body_lower:
                logger.debug("AccountDetector: matched auth pattern '%s'", keyword)
                return reason

        # Instant skip patterns
        for keyword, reason in _INSTANT_SKIP_PATTERNS:
            if keyword in body_lower:
                logger.debug("AccountDetector: matched skip pattern '%s'", keyword)
                return reason

        return None

    async def _check_dom(self, page: Page) -> str | None:
        """Check for auth-wall DOM selectors."""
        for selector in _AUTH_DOM_SELECTORS:
            try:
                el = page.locator(selector).first
                count = await el.count()
                if count > 0 and await el.is_visible():
                    logger.debug(
                        "AccountDetector: auth DOM selector visible: '%s'", selector
                    )
                    return "ACCOUNT_REQUIRED"
            except Exception:
                continue
        return None

    async def is_upload_page_blocked(self, page: Page) -> bool:
        """
        Quick check: is the current page asking for account creation
        specifically to continue the upload/application?
        """
        reason = await self.detect(page)
        return reason is not None


# ── Singleton ─────────────────────────────────────────────────────────────────

_detector: AccountDetector | None = None


def get_account_detector() -> AccountDetector:
    """Return the application-wide singleton AccountDetector."""
    global _detector
    if _detector is None:
        _detector = AccountDetector()
    return _detector
