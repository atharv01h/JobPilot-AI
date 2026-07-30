"""Naukri.com scraper."""

from __future__ import annotations

from datetime import datetime, timezone

from playwright.async_api import Page

from core.logger import get_logger
from core.models import Job
from scrapers.base_scraper import BaseScraper

logger = get_logger(__name__)


class NaukriScraper(BaseScraper):
    SOURCE = "Naukri"
    BASE_URL = "https://www.naukri.com/"

    async def scrape_playwright(
        self, page: Page, keyword: str, location: str
    ) -> list[Job]:
        """Deterministic Playwright scraper for Naukri."""
        logger.info(
            "Naukri: Starting deterministic scraping for '%s' in '%s'",
            keyword,
            location,
        )

        # Clean slugs for URL
        keyword_slug = keyword.replace(" ", "-").lower()
        location_slug = location.replace(" ", "-").lower()

        # Naukri direct search URL with experience = 0 to 2 yrs and last 7 days posting filters
        url = f"https://www.naukri.com/{keyword_slug}-jobs-in-{location_slug}?experience=0&experience=1&experience=2&days=7"

        await page.goto(url, timeout=25000, wait_until="domcontentloaded")

        try:
            await page.wait_for_selector(
                "div.srp-jobtuple-container, article.jobTuple, div.cust-job-tuple, div.list",
                timeout=12000,
            )
        except Exception:
            logger.warning(
                "Naukri: Search results selector did not load within timeout."
            )

        jobs: list[Job] = []

        # Selectors matching both newer and older layout formats
        cards = await page.locator(
            "div.srp-jobtuple-container, article.jobTuple, div.cust-job-tuple"
        ).all()
        for card in cards:
            try:
                title_el = card.locator("a.title, a.title.fw500, .title").first
                if await title_el.count() == 0:
                    continue
                title = (await title_el.inner_text()).strip()
                href = await title_el.get_attribute("href")
                if not href:
                    continue

                company_el = card.locator("a.subTitle, .comp-name, .subTitle").first
                company = (
                    (await company_el.inner_text()).strip()
                    if await company_el.count() > 0
                    else "Unknown"
                )

                loc_el = card.locator(
                    "span.locWdth, .loc-wrap, .location, span.loc"
                ).first
                loc = (
                    (await loc_el.inner_text()).strip()
                    if await loc_el.count() > 0
                    else location
                )

                exp_el = card.locator(
                    "span.exp-wrap, .experience, .exp, span.exp"
                ).first
                exp = (
                    (await exp_el.inner_text()).strip()
                    if await exp_el.count() > 0
                    else "0-2 Yrs"
                )

                sal_el = card.locator("span.sal-wrap, .salary, .sal, span.sal").first
                salary = (
                    (await sal_el.inner_text()).strip()
                    if await sal_el.count() > 0
                    else "Not disclosed"
                )

                jobs.append(
                    Job(
                        title=title,
                        company=company,
                        location=loc,
                        experience=exp,
                        salary=salary,
                        url=href,
                        source=self.SOURCE,
                        description=f"Job posting for {title} at {company} in {loc}. Experience: {exp}",
                        requirements="",
                        skills="",
                        posted_date="",
                        discovered_date=datetime.now(timezone.utc).isoformat(),
                    )
                )
            except Exception as card_err:
                logger.debug("Naukri: card parse error: %s", card_err)

        logger.info("Naukri: deterministic scraping found %d jobs", len(jobs))
        return jobs
