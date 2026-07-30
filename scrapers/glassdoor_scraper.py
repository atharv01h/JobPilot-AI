"""Glassdoor India scraper."""

from __future__ import annotations

import urllib.parse
from datetime import datetime, timezone

from playwright.async_api import Page

from core.logger import get_logger
from core.models import Job
from scrapers.base_scraper import BaseScraper

logger = get_logger(__name__)


class GlassdoorScraper(BaseScraper):
    SOURCE = "Glassdoor"
    BASE_URL = "https://www.glassdoor.co.in/Job/index.htm"

    async def scrape_playwright(
        self, page: Page, keyword: str, location: str
    ) -> list[Job]:
        """Deterministic Playwright scraper for Glassdoor."""
        logger.info(
            "Glassdoor: Starting deterministic scraping for '%s' in '%s'",
            keyword,
            location,
        )

        q_encoded = urllib.parse.quote(keyword)
        # Glassdoor direct search using query keywords
        url = f"https://www.glassdoor.co.in/Job/jobs.htm?sc.keyword={q_encoded}"

        await page.goto(url, timeout=25000, wait_until="domcontentloaded")

        try:
            await page.wait_for_selector(
                "[data-test='job-listing'], li.react-job-listing, .JobsList_jobListItem__vBND8",
                timeout=12000,
            )
        except Exception:
            logger.warning(
                "Glassdoor: Search results selector did not load within timeout."
            )

        jobs: list[Job] = []

        cards = await page.locator(
            "[data-test='job-listing'], li.react-job-listing, .JobsList_jobListItem__vBND8"
        ).all()
        for card in cards:
            try:
                title_el = card.locator(
                    "[data-test='job-title'], a.job-title, .JobCard_jobTitle___72rT"
                ).first
                if await title_el.count() == 0:
                    continue
                title = (await title_el.inner_text()).strip()
                href = await title_el.get_attribute("href")
                if not href:
                    continue
                if not href.startswith("http"):
                    href = "https://www.glassdoor.co.in" + href

                company_el = card.locator(
                    "[data-test='employer-short-name'], .employer-name, .EmployerProfile_employerName__8w0df"
                ).first
                company = (
                    (await company_el.inner_text()).strip()
                    if await company_el.count() > 0
                    else "Unknown"
                )
                if "\n" in company:
                    company = company.split("\n")[0]

                loc_el = card.locator(
                    "[data-test='location'], .location, .JobCard_location__r01nC"
                ).first
                loc = (
                    (await loc_el.inner_text()).strip()
                    if await loc_el.count() > 0
                    else location
                )

                sal_el = card.locator(
                    "[data-test='detailSalary'], .salary-estimate, .JobCard_salaryEstimate__ar55H"
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
                        url=href,
                        source=self.SOURCE,
                        description=f"Job posting for {title} at {company} in {loc}",
                        requirements="",
                        skills="",
                        posted_date="",
                        discovered_date=datetime.now(timezone.utc).isoformat(),
                    )
                )
            except Exception as card_err:
                logger.debug("Glassdoor: card parse error: %s", card_err)

        logger.info("Glassdoor: deterministic scraping found %d jobs", len(jobs))
        return jobs
