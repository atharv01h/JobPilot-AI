"""Foundit (formerly Monster India) job scraper."""

from __future__ import annotations

import urllib.parse
from datetime import datetime, timezone

from playwright.async_api import Page

from core.logger import get_logger
from core.models import Job
from scrapers.base_scraper import BaseScraper

logger = get_logger(__name__)


class FounditScraper(BaseScraper):
    SOURCE = "Foundit"
    BASE_URL = "https://www.foundit.in/"

    async def scrape_playwright(
        self, page: Page, keyword: str, location: str
    ) -> list[Job]:
        """Deterministic Playwright scraper for Foundit."""
        logger.info(
            "Foundit: Starting deterministic scraping for '%s' in '%s'",
            keyword,
            location,
        )

        q_encoded = urllib.parse.quote(keyword)
        l_encoded = urllib.parse.quote(location)

        # Foundit search URL with experience = 0 to 2 yrs and limit = 20
        url = f"https://www.foundit.in/srp/results?query={q_encoded}&locations={l_encoded}&experienceRanges=0~2&experienceRanges=0~0&experienceRanges=1~2&limit=20"

        await page.goto(url, timeout=25000, wait_until="domcontentloaded")

        try:
            await page.wait_for_selector(
                "div.srpCard, div.card-container, .srpCard-info", timeout=12000
            )
        except Exception:
            logger.warning(
                "Foundit: Search results selector did not load within timeout."
            )

        jobs: list[Job] = []

        cards = await page.locator(
            "div.srpCard, div.card-container, .srpCard-info"
        ).all()
        for card in cards:
            try:
                title_el = card.locator(
                    ".jobTitle a, .title a, a.title, div.jobTitle a"
                ).first
                if await title_el.count() == 0:
                    continue
                title = (await title_el.inner_text()).strip()
                href = await title_el.get_attribute("href")
                if not href:
                    continue
                if not href.startswith("http"):
                    href = "https://www.foundit.in" + href

                company_el = card.locator(
                    ".companyName a, .company-name, div.companyName, .companyName"
                ).first
                company = (
                    (await company_el.inner_text()).strip()
                    if await company_el.count() > 0
                    else "Unknown"
                )

                loc_el = card.locator(".location, div.location, .loc").first
                loc = (
                    (await loc_el.inner_text()).strip()
                    if await loc_el.count() > 0
                    else location
                )

                exp_el = card.locator(".exp, div.exp").first
                exp = (
                    (await exp_el.inner_text()).strip()
                    if await exp_el.count() > 0
                    else "0-2 Yrs"
                )

                sal_el = card.locator(".salary, div.salary").first
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
                logger.debug("Foundit: card parse error: %s", card_err)

        logger.info("Foundit: deterministic scraping found %d jobs", len(jobs))
        return jobs
