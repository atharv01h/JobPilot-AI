"""
CAPTCHA and verification handler.
Detects challenges, notifies user, and waits for resolution.

THREAD-SAFETY FIX:
  asyncio.Event objects are paired with their creating event loop.
  When the GUI (Tkinter thread) resolves a CAPTCHA/OTP, it uses
  loop.call_soon_threadsafe(event.set) instead of calling event.set()
  directly — preventing the "Future attached to a different loop" error.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from core.logger import get_logger

logger = get_logger(__name__)

CAPTCHA_KEYWORDS = [
    "captcha",
    "recaptcha",
    "hcaptcha",
    "verify you are human",
    "i'm not a robot",
    "are you a robot",
    "complete the captcha",
    "human verification",
    "security check",
    "prove you're human",
    "cloudflare",
    "bot protection",
    "ddos protection",
]

LOGIN_KEYWORDS = [
    "sign in",
    "log in",
    "login",
    "please log in",
    "please sign in",
    "authentication required",
    "account required",
]

OTP_KEYWORDS = [
    "otp",
    "one time password",
    "enter otp",
    "verification code",
    "sms code",
    "phone verification",
    "email verification",
    "verify your phone",
    "verify your email",
]

STOP_KEYWORDS = [
    "assessment test",
    "coding test",
    "coding challenge",
    "aptitude test",
    "video interview",
    "payment required",
    "purchase required",
]


def _make_event() -> tuple[asyncio.Event, asyncio.AbstractEventLoop]:
    """
    Create a fresh asyncio.Event bound to the currently-running event loop.
    Returns (event, loop) so callers can use loop.call_soon_threadsafe(event.set).
    """
    loop = asyncio.get_event_loop()
    return asyncio.Event(), loop


class CaptchaHandler:
    """
    Monitors for CAPTCHA, OTP, login, and stop conditions.

    Provides async pause points that block the agent until the user
    resolves the challenge in the GUI. All cross-thread signalling
    uses call_soon_threadsafe() to be event-loop safe.
    """

    def __init__(self) -> None:
        # (event, loop) pairs — created fresh each time handle_*() is called
        self._captcha_event: asyncio.Event | None = None
        self._captcha_loop: asyncio.AbstractEventLoop | None = None

        self._otp_event: asyncio.Event | None = None
        self._otp_loop: asyncio.AbstractEventLoop | None = None

        self._login_event: asyncio.Event | None = None
        self._login_loop: asyncio.AbstractEventLoop | None = None

        self._current_url: str = ""
        self._otp_value: str = ""

        # GUI callbacks set externally by gui/app.py
        self.on_captcha_detected: Callable[[str], None] | None = None
        self.on_otp_detected: Callable[[], None] | None = None
        self.on_login_detected: Callable[[], None] | None = None
        self.on_stop_detected: Callable[[str], None] | None = None

    # ── Detection ─────────────────────────────────────────────────────────────

    def detect_page_type(self, page_text: str, url: str = "") -> str:
        """
        Analyse page text and return:
        'normal' | 'captcha' | 'otp' | 'login' | 'stop'
        """
        text = page_text.lower()
        if any(kw in text for kw in CAPTCHA_KEYWORDS):
            return "captcha"
        if any(kw in text for kw in OTP_KEYWORDS):
            return "otp"
        if any(kw in text for kw in STOP_KEYWORDS):
            return "stop"
        if any(kw in text for kw in LOGIN_KEYWORDS):
            return "login"
        return "normal"

    # ── CAPTCHA flow ──────────────────────────────────────────────────────────

    async def handle_captcha(self, url: str) -> bool:
        """
        Pause automation until user resolves CAPTCHA.
        Thread-safe: resolve_captcha() can be called from any thread.
        """
        self._current_url = url
        self._captcha_event, self._captcha_loop = _make_event()
        logger.warning("CAPTCHA detected at: %s", url)

        if self.on_captcha_detected:
            self.on_captcha_detected(url)

        await self._captcha_event.wait()
        logger.info("CAPTCHA resolved — resuming automation")
        return True

    def resolve_captcha(self) -> None:
        """
        Called by the GUI (Tkinter thread) when user completes CAPTCHA.
        Uses call_soon_threadsafe to safely signal the async loop.
        """
        if self._captcha_event and self._captcha_loop:
            self._captcha_loop.call_soon_threadsafe(self._captcha_event.set)

    # ── OTP flow ──────────────────────────────────────────────────────────────

    async def handle_otp(self) -> str:
        """
        Pause until user provides the OTP.
        First attempts automatic extraction from Gmail via CDP.
        """
        self._otp_value = ""
        self._otp_event, self._otp_loop = _make_event()
        logger.warning("OTP request detected")

        # Attempt automatic OTP retrieval from Gmail
        try:
            from automation.browser_manager import get_browser_manager

            bm = get_browser_manager()
            site_name = "linkedin"
            url_lower = self._current_url.lower()
            if "naukri" in url_lower:
                site_name = "naukri"
            elif "indeed" in url_lower:
                site_name = "indeed"
            elif "glassdoor" in url_lower:
                site_name = "glassdoor"
            elif "gmail" in url_lower or "google" in url_lower:
                site_name = "google"

            otp = await bm.retrieve_gmail_otp_automatic(site_name)
            if otp:
                logger.info("Auto-OTP: retrieved OTP automatically.")
                self._otp_value = otp
                return otp
        except Exception as exc:
            logger.debug("Auto-OTP retrieval failed: %s", exc)

        # Fall back to manual OTP entry dialog
        if self.on_otp_detected:
            self.on_otp_detected()

        await self._otp_event.wait()
        logger.info("OTP received (manual entry).")
        return self._otp_value

    def resolve_otp(self, otp: str) -> None:
        """
        Called by the GUI (Tkinter thread) when user submits OTP.
        Thread-safe.
        """
        self._otp_value = otp
        if self._otp_event and self._otp_loop:
            self._otp_loop.call_soon_threadsafe(self._otp_event.set)

    # ── Login flow ────────────────────────────────────────────────────────────

    async def handle_login(self) -> None:
        """Pause until user has signed in manually."""
        self._login_event, self._login_loop = _make_event()
        logger.warning("Login required — waiting for user")

        if self.on_login_detected:
            self.on_login_detected()

        await self._login_event.wait()
        logger.info("Login confirmed — resuming")

    def resolve_login(self) -> None:
        """
        Called by the GUI (Tkinter thread) when user confirms sign-in.
        Thread-safe.
        """
        if self._login_event and self._login_loop:
            self._login_loop.call_soon_threadsafe(self._login_event.set)

    # ── Stop condition ────────────────────────────────────────────────────────

    def handle_stop_condition(self, reason: str) -> None:
        """Called when automation must stop (assessment, payment, etc.)."""
        logger.warning("Stop condition detected: %s", reason)
        if self.on_stop_detected:
            self.on_stop_detected(reason)

    @property
    def current_url(self) -> str:
        return self._current_url


# ── Singleton ─────────────────────────────────────────────────────────────────

_captcha_handler: CaptchaHandler | None = None


def get_captcha_handler() -> CaptchaHandler:
    global _captcha_handler
    if _captcha_handler is None:
        _captcha_handler = CaptchaHandler()
    return _captcha_handler
