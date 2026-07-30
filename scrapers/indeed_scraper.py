"""Indeed India scraper."""

from __future__ import annotations

import urllib.parse
from datetime import datetime, timezone

from playwright.async_api import Page

from core.logger import get_logger
from core.models import Job
from scrapers.base_scraper import BaseScraper

logger = get_logger(__name__)


class IndeedScraper(BaseScraper):
    SOURCE = "Indeed"
    BASE_URL = "https://in.indeed.com/"

    async def scrape_playwright(
        self, page: Page, keyword: str, location: str
    ) -> list[Job]:
        """Deterministic Playwright scraper for Indeed."""
        logger.info(
            "Indeed: Starting deterministic scraping for '%s' in '%s'",
            keyword,
            location,
        )

        q_encoded = urllib.parse.quote(keyword)
        l_encoded = urllib.parse.quote(location)

        # Indeed India search URL with Entry Level and last 7 days filters
        url = f"https://in.indeed.com/jobs?q={q_encoded}&l={l_encoded}&fromage=7&sc=0kf%3Aexplvl%28ENTRY_LEVEL%29%3B"

        await page.goto(url, timeout=25000, wait_until="domcontentloaded")

        try:
            await page.wait_for_selector(
                "div.job_seen_beacon, td.resultContent, div.cardOutline", timeout=12000
            )
        except Exception:
            logger.warning(
                "Indeed: Search results selector did not load within timeout."
            )

        jobs: list[Job] = []

        cards = await page.locator(
            "div.job_seen_beacon, td.resultContent, div.cardOutline"
        ).all()
        for card in cards:
            try:
                title_el = card.locator("h2.jobTitle a, a.jcs-JobTitle").first
                if await title_el.count() == 0:
                    continue
                title = (await title_el.inner_text()).strip()
                if title.lower().startswith("new\n"):
                    title = title[4:]

                href = await title_el.get_attribute("href")
                if not href:
                    continue
                if not href.startswith("http"):
                    href = "https://in.indeed.com" + href
                url_clean = href.split("&")[0] if href else ""
                if not url_clean:
                    continue

                company_el = card.locator(
                    "span[data-testid='company-name'], span.companyName, .companyName"
                ).first
                company = (
                    (await company_el.inner_text()).strip()
                    if await company_el.count() > 0
                    else "Unknown"
                )

                loc_el = card.locator(
                    "div[data-testid='text-location'], div.companyLocation, .companyLocation"
                ).first
                loc = (
                    (await loc_el.inner_text()).strip()
                    if await loc_el.count() > 0
                    else location
                )

                sal_el = card.locator(
                    "div.metadata.salary-snippet-container, div.salary-snippet, [data-testid='attribute_snippet_salary']"
                ).first
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
                        experience="Entry Level / Fresher (0-2 years)",
                        salary=salary,
                        url=url_clean,
                        source=self.SOURCE,
                        description=f"Job posting for {title} at {company} in {loc}",
                        requirements="",
                        skills="",
                        posted_date="",
                        discovered_date=datetime.now(timezone.utc).isoformat(),
                    )
                )
            except Exception as card_err:
                logger.debug("Indeed: card parse error: %s", card_err)

        logger.info("Indeed: deterministic scraping found %d jobs", len(jobs))
        return jobs
