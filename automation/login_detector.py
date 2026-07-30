"""
login_detector.py — Multi-signal login state detector.

Instead of relying on single selector checks, this class evaluates multiple independent
signals (DOM state, URL, cookies, storage, etc.) to determine if the user is authenticated.
"""

from __future__ import annotations

import asyncio

from playwright.async_api import Page

from core.logger import get_logger

logger = get_logger(__name__)


class LoginStateDetector:
    """
    Evaluates authentication states across supported job boards using multiple signals.
    """

    def __init__(self) -> None:
        # Multi-signal rules per site
        self.rules: dict[str, dict] = {
            "linkedin": {
                "check_url": "https://www.linkedin.com/feed/",
                "cookies": ["li_at", "li_theme"],
                "selectors_high": [
                    ".global-nav__me-photo",
                    "button.global-nav__primary-link:has-text('Me')",
                    "a[href*='/notifications']",
                    "a[href*='/messaging']",
                    "button:has-text('Start a post')",
                    "a[href*='/logout']",
                ],
                "selectors_medium": [".feed-identity-module", ".global-nav__nav"],
            },
            "naukri": {
                "check_url": "https://www.naukri.com/mnjuser/homepage",
                "cookies": ["nupg", "nprofile"],
                "selectors_high": [
                    "a[href*='logout']",
                    "a:has-text('Logout')",
                    ".update-profile",
                    "a:has-text('Update profile')",
                ],
                "selectors_medium": [
                    "div.homepage-container",
                    "span:has-text('Recommended jobs')",
                    ".nLogo",
                ],
            },
            "indeed": {
                "check_url": "https://in.indeed.com/",
                "cookies": ["INDEED_USER_SECURE", "Indeed_Session"],
                "selectors_high": [
                    "a[href*='signout']",
                    "a:has-text('Sign out')",
                    "a[href*='/profile']",
                    "button[id*='user-menu']",
                    ".gnav-ProfileMenu",
                ],
                "selectors_medium": [
                    "a:has-text('My jobs')",
                    ".gnav-LoggedinContainer",
                ],
            },
            "foundit": {
                "check_url": "https://www.foundit.in/mnjuser/dashboard",
                "cookies": ["mnj_logged_in"],
                "selectors_high": [
                    "a[href*='logout']",
                    "a:has-text('Logout')",
                    "a:has-text('My Profile')",
                ],
                "selectors_medium": [
                    "div.dashboard-container",
                    "span:has-text('Recommended Jobs')",
                ],
            },
            "glassdoor": {
                "check_url": "https://www.glassdoor.co.in/member/profile/index.htm",
                "cookies": ["gdId", "asst"],
                "selectors_high": ["a[href*='logout']", "a:has-text('Sign Out')"],
                "selectors_medium": [
                    "div.jobAlertsHeader",
                    "a:has-text('Resumes')",
                    "h2:has-text('Job Alerts')",
                ],
            },
            "wellfound": {
                "check_url": "https://wellfound.com/jobs",
                "cookies": ["oauth_token"],
                "selectors_high": [
                    "a[href*='/logout']",
                    "button:has-text('Log out')",
                    "a[href*='/messages']",
                    "img[alt*='avatar']",
                    "a[href*='/settings']",
                ],
                "selectors_medium": [
                    "[class*='UserHeader']",
                    "[class*='header-avatar']",
                ],
            },
            "instahyre": {
                "check_url": "https://www.instahyre.com/candidate/opportunities/",
                "cookies": ["sessionid"],
                "selectors_high": [
                    "a[href*='logout']",
                    "a:has-text('Logout')",
                    "a[href*='/candidate/profile']",
                ],
                "selectors_medium": [
                    "div:has-text('Opportunities')",
                    "span.resume-score",
                ],
            },
        }

    async def is_logged_in(self, site: str, page: Page) -> bool:
        """
        Check if the user is logged in to a specific site.
        Evaluates cookies, current URL, session storage, and multiple selectors.
        Returns True if score >= 3.
        """
        site_key = site.lower()
        rule = self.rules.get(site_key)
        if not rule:
            logger.warning("No login check rules for site: %s", site)
            return False

        logger.info("Evaluating login state for %s...", site)

        score = 0
        details = []

        # 1. URL Signal: Are we already on target page or feed/dashboard?
        curr_url = page.url.lower()
        target_check = rule["check_url"].lower()
        if (
            target_check in curr_url
            or "feed" in curr_url
            or "dashboard" in curr_url
            or "homepage" in curr_url
            or "opportunities" in curr_url
        ):
            score += 2
            details.append("URL matches active session patterns (Score +2)")

        # 2. Cookie Signal: Are expected auth cookies present?
        try:
            cookies = await page.context.cookies()
            cookie_names = [c["name"] for c in cookies]
            matching_cookies = [c for c in rule["cookies"] if c in cookie_names]
            if len(matching_cookies) >= 1:
                score += 2
                details.append(f"Auth cookies present: {matching_cookies} (Score +2)")
        except Exception as exc:
            logger.debug("Failed to retrieve cookies: %s", exc)

        # 3. Session/Local Storage Signal
        try:
            has_storage = await page.evaluate("""(() => {
                try {
                    return Object.keys(sessionStorage).length > 0 || Object.keys(localStorage).length > 0;
                } catch(e) {
                    return false;
                }
            })()""")
            if has_storage:
                score += 1
                details.append("Active session/local storage found (Score +1)")
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)

        # 4. High-confidence DOM Selectors
        for selector in rule.get("selectors_high", []):
            try:
                locator = page.locator(selector).first
                if await locator.count() > 0 and await locator.is_visible():
                    score += 3
                    details.append(f"High-conf selector found: {selector} (Score +3)")
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

        # 5. Medium-confidence DOM Selectors
        for selector in rule.get("selectors_medium", []):
            try:
                locator = page.locator(selector).first
                if await locator.count() > 0 and await locator.is_visible():
                    score += 1.5
                    details.append(f"Med-conf selector found: {selector} (Score +1.5)")
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

        logger.info(
            "%s login evaluation score: %.1f. Details: %s", site, score, details
        )

        authenticated = score >= 3.0
        logger.info(
            "%s status: %s", site, "LOGGED_IN" if authenticated else "LOGGED_OUT"
        )
        return authenticated

    async def debug_check(self) -> None:
        """Helper tool for validating the detector output."""
        from automation.browser_session_pool import get_browser_session_pool

        pool = get_browser_session_pool()
        page = await pool.get_page()
        try:
            for site in self.rules:
                rule = self.rules[site]
                await page.goto(
                    rule["check_url"], timeout=15000, wait_until="domcontentloaded"
                )
                await asyncio.sleep(2)
                res = await self.is_logged_in(site, page)
                print(f"Debug Check -> Site: {site.upper()} | Logged In: {res}")
        finally:
            await page.close()


# ── Singleton ─────────────────────────────────────────────────────────────────

_detector: LoginStateDetector | None = None


def get_login_detector() -> LoginStateDetector:
    global _detector
    if _detector is None:
        _detector = LoginStateDetector()
    return _detector
