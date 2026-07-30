"""
website_strategies.py — Dedicated site-specific automation strategies.

Isolates CSS/XPath selectors, navigation urls, search triggers, and apply actions
for each supported job board to prevent selector leakage or cross-site conflicts.
"""

from __future__ import annotations

from playwright.async_api import Page

from core.logger import get_logger

logger = get_logger(__name__)


class BaseStrategy:
    """Base class for all site-specific interaction strategies."""

    NAME: str = "Unknown"
    BASE_URL: str = ""

    def get_search_url(self, keyword: str, location: str) -> str:
        raise NotImplementedError

    def get_selectors(self) -> dict[str, str]:
        raise NotImplementedError

    async def detect_state(self, page: Page) -> str:
        """Determines the current state of the page using selectors and URL heuristics."""
        return "UNKNOWN"


class LinkedInStrategy(BaseStrategy):
    NAME = "LinkedIn"
    BASE_URL = "https://www.linkedin.com/jobs/"

    def get_search_url(self, keyword: str, location: str) -> str:
        import urllib.parse

        q = urllib.parse.quote(keyword)
        l = urllib.parse.quote(location)
        return f"https://www.linkedin.com/jobs/search/?keywords={q}&location={l}&f_TPR=r604800&f_E=1%2C2"

    def get_selectors(self) -> dict[str, str]:
        return {
            "job_card": "li.jobs-search-results-list__list-item, .job-card-container",
            "title": "a.job-card-list__title, .job-card-container__link",
            "company": "span.job-card-container__primary-description, .artdeco-entity-lockup__subtitle",
            "location": "li.job-card-container__metadata-item",
            "apply_button": "button.jobs-apply-button",
            "submit_button": "button:has-text('Submit application')",
            "next_button": "button:has-text('Next')",
        }

    async def detect_state(self, page: Page) -> str:
        url = page.url.lower()
        if "login" in url or "checkpoint" in url:
            return "LOGIN_CHECK"

        # Check if easy apply modal is open
        if (
            await page.locator(
                "div.jobs-easy-apply-modal, [class*='easy-apply-modal']"
            ).count()
            > 0
        ):
            modal = page.locator(
                "div.jobs-easy-apply-modal, [class*='easy-apply-modal']"
            ).first
            # Within the modal, check the step
            if await modal.locator("input[type='file']").count() > 0:
                return "UPLOAD"
            if (
                await modal.locator(
                    "button:has-text('Submit application'), button:has-text('Submit')"
                ).count()
                > 0
            ):
                return "SUBMIT"
            if (
                await modal.locator(
                    "li.jobs-easy-apply-modal__check-icon, .artdeco-inline-feedback--success, :has-text('Application submitted')"
                ).count()
                > 0
            ):
                return "CONFIRMATION"
            return "FORM"

        # Check if job details pane is open
        if (
            "jobs/view/" in url
            or await page.locator(
                ".jobs-search__job-details, .jobs-details-toggle, [class*='job-details']"
            ).count()
            > 0
        ):
            return "JOB_DETAILS"

        if "jobs/search" in url:
            if (
                await page.locator(
                    "li.jobs-search-results-list__list-item, .job-card-container"
                ).count()
                > 0
            ):
                return "SEARCH_RESULTS"
            return "JOB_SEARCH"

        if "feed" in url or "dashboard" in url:
            return "HOME"

        from automation.login_detector import get_login_detector

        ld = get_login_detector()
        if not await ld.is_logged_in("linkedin", page):
            return "LOGIN_CHECK"

        return "HOME"


class NaukriStrategy(BaseStrategy):
    NAME = "Naukri"
    BASE_URL = "https://www.naukri.com/"

    def get_search_url(self, keyword: str, location: str) -> str:
        kw_part = keyword.lower().replace(" ", "-")
        loc_part = location.lower().replace(" ", "-")
        return f"https://www.naukri.com/{kw_part}-jobs-in-{loc_part}"

    def get_selectors(self) -> dict[str, str]:
        return {
            "job_card": "article.jobTuple, div.cust-job-tuple",
            "title": "a.title, a.job-title",
            "company": "a.comp-name, .company-name",
            "location": "span.loc-wrap, .location-text",
            "apply_button": "button#apply-button, button.apply-button",
            "submit_button": "button:has-text('Submit')",
        }

    async def detect_state(self, page: Page) -> str:
        url = page.url.lower()
        if "login" in url:
            return "LOGIN_CHECK"

        if (
            "naukri.com/apply" in url
            or await page.locator("div.apply-modal, div.ats-apply-container").count()
            > 0
        ):
            if await page.locator("input[type='file']").count() > 0:
                return "UPLOAD"
            if (
                await page.locator(
                    "button:has-text('Submit'), button:has-text('Apply')"
                ).count()
                > 0
            ):
                return "SUBMIT"
            return "FORM"

        if "mnjuser/homepage" in url or "naukri.com/homepage" in url:
            return "HOME"

        if "naukri.com" in url:
            if ("-jobs" in url or "search" in url) and (
                await page.locator("article.jobTuple, div.cust-job-tuple").count()
                > 0
            ):
                return "SEARCH_RESULTS"
            return "JOB_SEARCH"

        from automation.login_detector import get_login_detector

        ld = get_login_detector()
        if not await ld.is_logged_in("naukri", page):
            return "LOGIN_CHECK"

        return "HOME"


class IndeedStrategy(BaseStrategy):
    NAME = "Indeed"
    BASE_URL = "https://in.indeed.com/"

    def get_search_url(self, keyword: str, location: str) -> str:
        import urllib.parse

        q = urllib.parse.quote(keyword)
        l = urllib.parse.quote(location)
        return f"https://in.indeed.com/jobs?q={q}&l={l}&fromage=7"

    def get_selectors(self) -> dict[str, str]:
        return {
            "job_card": "div.job_seen_beacon, td.resultContent",
            "title": "h2.jobTitle a, span[id^='jobVal']",
            "company": "span[data-testid='company-name']",
            "location": "div[data-testid='text-location']",
            "apply_button": "button.ia-IndeedApplyButton",
            "submit_button": "button:has-text('Submit your application')",
        }

    async def detect_state(self, page: Page) -> str:
        url = page.url.lower()
        if "login" in url or "signin" in url:
            return "LOGIN_CHECK"

        if (
            "indeedapply" in url
            or await page.locator(
                "div.ia-IndeedApplyButton, iframe[src*='indeedapply']"
            ).count()
            > 0
        ):
            if await page.locator("input[type='file']").count() > 0:
                return "UPLOAD"
            if (
                await page.locator(
                    "button:has-text('Submit'), button:has-text('Submit your application')"
                ).count()
                > 0
            ):
                return "SUBMIT"
            return "FORM"

        if "viewjob" in url:
            return "JOB_DETAILS"

        if "jobs" in url or "q=" in url:
            if await page.locator("div.job_seen_beacon, td.resultContent").count() > 0:
                return "SEARCH_RESULTS"
            return "JOB_SEARCH"

        from automation.login_detector import get_login_detector

        ld = get_login_detector()
        if not await ld.is_logged_in("indeed", page):
            return "LOGIN_CHECK"

        return "HOME"


class FounditStrategy(BaseStrategy):
    NAME = "Foundit"
    BASE_URL = "https://www.foundit.in/"

    def get_search_url(self, keyword: str, location: str) -> str:
        import urllib.parse

        q = urllib.parse.quote(keyword)
        l = urllib.parse.quote(location)
        return f"https://www.foundit.in/srp/results?query={q}&locations={l}"

    def get_selectors(self) -> dict[str, str]:
        return {
            "job_card": "div.cardContent, div.job-tuple",
            "title": "div.jobTitle, a.job-title",
            "company": "div.companyName, a.company-name",
            "location": "div.location, span.loc",
            "apply_button": "button:has-text('Apply'), a.apply-btn",
            "submit_button": "button:has-text('Submit')",
        }

    async def detect_state(self, page: Page) -> str:
        url = page.url.lower()
        if "login" in url or "signin" in url:
            return "LOGIN_CHECK"

        if "apply" in url or await page.locator("div.apply-container").count() > 0:
            if await page.locator("input[type='file']").count() > 0:
                return "UPLOAD"
            if await page.locator("button:has-text('Submit')").count() > 0:
                return "SUBMIT"
            return "FORM"

        if "srp/results" in url or "search" in url:
            if await page.locator("div.cardContent, div.job-tuple").count() > 0:
                return "SEARCH_RESULTS"
            return "JOB_SEARCH"

        if "dashboard" in url:
            return "HOME"

        from automation.login_detector import get_login_detector

        ld = get_login_detector()
        if not await ld.is_logged_in("foundit", page):
            return "LOGIN_CHECK"

        return "HOME"


class GlassdoorStrategy(BaseStrategy):
    NAME = "Glassdoor"
    BASE_URL = "https://www.glassdoor.co.in/"

    def get_search_url(self, keyword: str, location: str) -> str:
        import urllib.parse

        q = urllib.parse.quote(keyword)
        return f"https://www.glassdoor.co.in/Job/jobs.htm?sc.keyword={q}"

    def get_selectors(self) -> dict[str, str]:
        return {
            "job_card": "li[data-test='jobListing']",
            "title": "a[data-test='job-title']",
            "company": "span[data-test='employer-name']",
            "location": "div[data-test='location']",
            "apply_button": "button[data-test='easy-apply']",
            "submit_button": "button:has-text('Submit Application')",
        }

    async def detect_state(self, page: Page) -> str:
        url = page.url.lower()
        if "login" in url or "member/profile" in url:
            return "LOGIN_CHECK"

        if "job" in url or "jobs" in url:
            if await page.locator("li[data-test='jobListing']").count() > 0:
                return "SEARCH_RESULTS"
            return "JOB_SEARCH"

        from automation.login_detector import get_login_detector

        ld = get_login_detector()
        if not await ld.is_logged_in("glassdoor", page):
            return "LOGIN_CHECK"

        return "HOME"


class WellfoundStrategy(BaseStrategy):
    NAME = "Wellfound"
    BASE_URL = "https://wellfound.com/"

    def get_search_url(self, keyword: str, location: str) -> str:
        return "https://wellfound.com/jobs"

    def get_selectors(self) -> dict[str, str]:
        return {
            "job_card": "[class*='JobCard'], [data-test='JobResult']",
            "title": "[class*='JobTitle'], [class*='title']",
            "company": "[class*='CompanyName'], [class*='company']",
            "location": "[class*='Location'], [class*='location']",
            "apply_button": "button:has-text('Apply'), [class*='ApplyButton']",
            "submit_button": "button:has-text('Submit Application')",
        }

    async def detect_state(self, page: Page) -> str:
        url = page.url.lower()
        if "login" in url or "join" in url:
            return "LOGIN_CHECK"

        if "jobs" in url:
            if (
                await page.locator(
                    "[class*='JobCard'], [data-test='JobResult']"
                ).count()
                > 0
            ):
                return "SEARCH_RESULTS"
            return "JOB_SEARCH"

        from automation.login_detector import get_login_detector

        ld = get_login_detector()
        if not await ld.is_logged_in("wellfound", page):
            return "LOGIN_CHECK"

        return "HOME"


class InstahyreStrategy(BaseStrategy):
    NAME = "Instahyre"
    BASE_URL = "https://www.instahyre.com/"

    def get_search_url(self, keyword: str, location: str) -> str:
        return "https://www.instahyre.com/candidate/opportunities/"

    def get_selectors(self) -> dict[str, str]:
        return {
            "job_card": ".job-card, .job-description, [class*='job-card']",
            "title": ".job-title, [class*='job-title']",
            "company": ".company-name, [class*='company-name']",
            "location": ".location-text, [class*='location']",
            "apply_button": "button:has-text('Apply'), .apply-button",
            "submit_button": "button:has-text('Submit')",
        }

    async def detect_state(self, page: Page) -> str:
        url = page.url.lower()
        if "login" in url or "signup" in url:
            return "LOGIN_CHECK"

        if "candidate/opportunities" in url:
            if await page.locator(".job-card, .job-description").count() > 0:
                return "SEARCH_RESULTS"
            return "JOB_SEARCH"

        from automation.login_detector import get_login_detector

        ld = get_login_detector()
        if not await ld.is_logged_in("instahyre", page):
            return "LOGIN_CHECK"

        return "HOME"


# Helper map of strategies
STRATEGIES: dict[str, BaseStrategy] = {
    "linkedin": LinkedInStrategy(),
    "naukri": NaukriStrategy(),
    "indeed": IndeedStrategy(),
    "foundit": FounditStrategy(),
    "glassdoor": GlassdoorStrategy(),
    "wellfound": WellfoundStrategy(),
    "instahyre": InstahyreStrategy(),
}


def get_strategy(site_name: str) -> BaseStrategy | None:
    return STRATEGIES.get(site_name.lower())
