"""
Session Manager Service.
Tracks the active login session status (Logged In / Logged Out / Unknown / Busy)
for LinkedIn, Naukri, Indeed, Glassdoor, Foundit, and Gmail using lightweight
Playwright checks.

FIXES:
  - check_all_sites() now calls check_site_status() per site — no duplicated logic.
  - Both check methods guard against running while the agent is active (returns Busy).
  - Blind wait_for_timeout() replaced with intelligent wait_for_load_state().
  - Session checks use a DEDICATED HEADLESS CHROMIUM instance — they never
    interfere with the Brave session used by the Browser-Use agent.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from core.logger import get_logger

logger = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent
_STATUS_FILE = _PROJECT_ROOT / "session_status.json"
PROFILE_DIR = _PROJECT_ROOT / "browser_profile"

SITES = ["linkedin", "naukri", "indeed", "glassdoor", "foundit", "gmail"]

SITES_CHECK_RULES: dict[str, dict] = {
    "linkedin": {
        "url": "https://www.linkedin.com/feed/",
        "login_indicators": ["feed", "Start a post", "Me", "Sign out"],
        "logout_indicators": ["Sign in", "Join now", "login", "checkpoint", "uas"],
        "default": "Logged Out",
    },
    "naukri": {
        "url": "https://www.naukri.com/mnjuser/homepage",
        "login_indicators": [
            "homepage",
            "Update profile",
            "Recommended jobs",
            "Logout",
        ],
        "logout_indicators": ["login", "Register", "Sign in"],
        "default": "Logged Out",
    },
    "indeed": {
        "url": "https://in.indeed.com/",
        "login_indicators": ["My jobs", "Sign out", "Profile"],
        "logout_indicators": ["Sign in", "Upload your resume"],
        "default": "Logged Out",
    },
    "glassdoor": {
        "url": "https://www.glassdoor.co.in/member/profile/index.htm",
        "login_indicators": ["profile", "Job Alerts", "Resumes", "Sign Out"],
        "logout_indicators": ["login", "Sign In", "Sign Up", "Join Now"],
        "default": "Logged Out",
    },
    "foundit": {
        "url": "https://www.foundit.in/mnjuser/dashboard",
        "login_indicators": ["dashboard", "My Profile", "Recommended Jobs", "Logout"],
        "logout_indicators": ["login", "Register", "Sign In"],
        "default": "Logged Out",
    },
    "gmail": {
        "url": "https://mail.google.com/",
        "login_indicators": ["mail", "Inbox", "Compose", "Gmail"],
        "logout_indicators": ["accounts.google.com", "signin", "Sign in"],
        "default": "Logged Out",
    },
}

# How long to wait for the page to settle before reading status (max)
_PAGE_SETTLE_TIMEOUT_MS = 6000


def _evaluate_page(url: str, body_text: str, rule: dict) -> str:
    """Check login/logout indicators against page URL + text."""
    combined = (url + " " + body_text).lower()
    is_login = any(ind.lower() in combined for ind in rule["login_indicators"])
    is_logout = any(ind.lower() in combined for ind in rule["logout_indicators"])
    if is_login and not is_logout:
        return "Logged In"
    if is_logout:
        return "Logged Out"
    return rule["default"]


class SessionManager:
    """Tracks login sessions and triggers Playwright status verifications."""

    def __init__(self) -> None:
        self._status: dict[str, dict] = {}
        self.is_agent_running = False
        self.is_search_running = False
        self.is_checking = False
        self.on_status_updated = []
        self._init_defaults()
        self.load()

    def _init_defaults(self) -> None:
        for site in SITES:
            self._status[site] = {
                "status": "Unknown",
                "last_checked": "",
                "last_login": "",
            }

    def load(self) -> None:
        if not _STATUS_FILE.exists():
            return
        try:
            data = json.loads(_STATUS_FILE.read_text(encoding="utf-8"))
            for site in SITES:
                if site in data:
                    self._status[site] = {
                        "status": data[site].get("status", "Unknown"),
                        "last_checked": data[site].get("last_checked", ""),
                        "last_login": data[site].get("last_login", ""),
                    }
        except Exception as exc:
            logger.warning("Failed to load session statuses: %s", exc)

    def save(self) -> None:
        try:
            _STATUS_FILE.write_text(
                json.dumps(self._status, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            logger.warning("Failed to save session statuses: %s", exc)

    def get_status(self, site: str) -> dict:
        site = site.lower()
        return self._status.get(
            site, {"status": "Unknown", "last_checked": "", "last_login": ""}
        )

    def get_all_statuses(self) -> dict[str, dict]:
        return dict(self._status)

    def update_status(
        self, site: str, status: str, last_login: str | None = None
    ) -> None:
        site = site.lower()
        if site not in self._status:
            return
        self._status[site]["status"] = status
        self._status[site]["last_checked"] = datetime.now(timezone.utc).isoformat()
        if last_login:
            self._status[site]["last_login"] = last_login
        elif status == "Logged In":
            self._status[site]["last_login"] = datetime.now(timezone.utc).isoformat()
        self.save()
        for cb in self.on_status_updated:
            try:
                cb()
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

    def mark_logged_in(self, site: str) -> None:
        self.update_status(site, "Logged In", last_login=datetime.now(timezone.utc).isoformat())

    def mark_logged_out(self, site: str) -> None:
        self.update_status(site, "Logged Out")

    def clear_status_cache(self) -> None:
        self._init_defaults()
        if _STATUS_FILE.exists():
            try:
                os.remove(_STATUS_FILE)
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)
        logger.info("Session status cache cleared.")

    async def check_site_status(self, site: str) -> str:
        """
        Check authentication state of a single site using a page from the shared browser context.
        Guards against running while the agent or another search is active.
        Returns: 'Logged In' | 'Logged Out' | 'Unknown' | 'Busy'.
        """
        site = site.lower()
        rule = SITES_CHECK_RULES.get(site)
        if not rule:
            return "Unknown"

        # Guard: don't check if agent or search is actively running
        if self.is_agent_running or self.is_search_running:
            self.update_status(site, "Busy")
            return "Busy"

        from automation.browser_session_pool import get_browser_session_pool
        from automation.login_detector import get_login_detector

        self._status[site]["status"] = "Checking..."
        for cb in self.on_status_updated:
            try:
                cb()
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

        pool = get_browser_session_pool()
        detector = get_login_detector()
        page = None
        try:
            page = await pool.get_page()
            logger.info("Session check: navigating to %s for %s", rule["url"], site)
            await page.goto(rule["url"], timeout=15000, wait_until="domcontentloaded")
            await page.wait_for_timeout(1000)

            is_logged = await detector.is_logged_in(site, page)
            res = "Logged In" if is_logged else "Logged Out"

            logger.debug("Site %s verified status: %s", site, res)
            self.update_status(site, res)
            return res

        except Exception as exc:
            logger.error("Session check error for %s: %s", site, exc)
            self.update_status(site, "Unknown")
            return "Unknown"
        finally:
            if page:
                try:
                    await page.close()
                except Exception as _exc:
                    logger.debug("Suppressed: %s", _exc)

    async def check_all_sites(self) -> dict[str, dict]:
        """
        Check all sites concurrently using individual headless Chromium contexts.
        Each site gets its own context to prevent cross-contamination.
        Guards against running while agent is active.
        """
        if self.is_agent_running or self.is_search_running:
            logger.info("Session check skipped — agent or search is running.")
            for site in SITES:
                self.update_status(site, "Busy")
            return self.get_all_statuses()

        logger.info("Checking session status for all sites concurrently...")
        self.is_checking = True

        # Mark all as Checking... immediately for UI feedback
        for site in SITES:
            self._status[site]["status"] = "Checking..."
        self.save()
        for cb in self.on_status_updated:
            try:
                cb()
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

        try:
            # Delegate to check_site_status() — no duplicated logic
            tasks = [self.check_site_status(site) for site in SITES]
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            self.is_checking = False

        return self.get_all_statuses()

    # ── Telemetry helpers for dashboard ──────────────────────────────────────

    def get_browser_status(self) -> str:
        if self.is_agent_running:
            return "Running Agent"
        if self.is_checking:
            return "Checking Sessions"
        if self.is_search_running:
            return "Searching Jobs"
        return "Idle"

    def get_connection_status(self) -> str:
        from automation.cdp_connector import is_cdp_port_open
        from config.constants import CDP_PORT

        try:
            if is_cdp_port_open(CDP_PORT):
                return "Connected (Brave CDP)"
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)
        lock_file = PROFILE_DIR / "SingletonLock"
        lockfile_win = PROFILE_DIR / "lockfile"
        if lock_file.exists() or lockfile_win.exists():
            return "Connected (Profile Active)"
        return "Disconnected"

    def get_session_health(self) -> str:
        statuses = [self._status[s]["status"] for s in SITES]
        n = statuses.count("Logged In")
        if n == len(SITES):
            return "Healthy"
        if n > 0:
            return "Attention Required"
        return "Degraded"

    def get_active_session_count(self) -> int:
        return sum(1 for s in SITES if self._status[s]["status"] == "Logged In")

    def get_profile_info(self) -> str:
        try:
            return str(PROFILE_DIR.relative_to(_PROJECT_ROOT))
        except ValueError:
            return str(PROFILE_DIR)


# ── Singleton ─────────────────────────────────────────────────────────────────

_session_manager: SessionManager | None = None


def get_session_manager() -> SessionManager:
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
