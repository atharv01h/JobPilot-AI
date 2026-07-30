"""LinkedIn Jobs scraper."""

from __future__ import annotations

import asyncio
import json
import urllib.parse
from datetime import datetime, timezone

from playwright.async_api import Page

from core.logger import get_logger
from core.models import Job
from scrapers.base_scraper import BaseScraper

logger = get_logger(__name__)


class LinkedInScraper(BaseScraper):
    SOURCE = "LinkedIn"
    BASE_URL = "https://www.linkedin.com/jobs/search/"

    async def scrape_playwright(
        self, page: Page, keyword: str, location: str
    ) -> list[Job]:
        """Deterministic Playwright scraper for LinkedIn (Logged in or logged out)."""
        logger.info(
            "LinkedIn: Starting deterministic scraping for '%s' in '%s'",
            keyword,
            location,
        )

        q_encoded = urllib.parse.quote(keyword)
        l_encoded = urllib.parse.quote(location)

        from config.settings import get_settings

        settings = get_settings()

        if getattr(settings, "linkedin_easy_apply_mode", False):
            # Dynamic URL based on Easy Apply Preferences
            from core.database import get_database

            prefs = {}
            try:
                db = get_database()
                prefs_raw = await db.get_memory("linkedin_easy_apply_preferences")
                if prefs_raw:
                    prefs = json.loads(prefs_raw)
            except Exception as exc:
                logger.debug(
                    "LinkedInScraper: Failed to load search preferences: %s", exc
                )

            url_parts = [f"keywords={q_encoded}", f"location={l_encoded}", "f_AL=true"]

            wts = []
            if prefs.get("onsite"):
                wts.append("1")
            if prefs.get("remote"):
                wts.append("2")
            if prefs.get("hybrid"):
                wts.append("3")
            if wts:
                url_parts.append(f"f_WT={','.join(wts)}")

            jts = []
            if prefs.get("fulltime"):
                jts.append("F")
            if prefs.get("parttime"):
                jts.append("P")
            if prefs.get("intern"):
                jts.append("I")
            if jts:
                url_parts.append(f"f_JT={','.join(jts)}")

            exp_map = {
                "Internship": "1",
                "Entry Level": "2",
                "Associate": "3",
                "Mid-Senior Level": "4",
                "Director": "5",
            }
            exp_pref = prefs.get("exp")
            if exp_pref and exp_pref in exp_map:
                url_parts.append(f"f_E={exp_map[exp_pref]}")

            date_map = {
                "Past 24 Hours": "r86400",
                "Past Week": "r604800",
                "Past Month": "r2592000",
            }
            date_pref = prefs.get("date")
            if date_pref and date_pref in date_map:
                url_parts.append(f"f_TPR={date_map[date_pref]}")
            else:
                url_parts.append("f_TPR=r604800")

            url = f"https://www.linkedin.com/jobs/search/?{'&'.join(url_parts)}"
        else:
            # Public search URL (often works logged out or redirects to logged in)
            url = f"https://www.linkedin.com/jobs/search/?keywords={q_encoded}&location={l_encoded}&f_TPR=r604800&f_E=1%2C2"

        jobs: list[Job] = []
        start_offset = 0
        max_pages = 8  # Traverse up to 8 pages per keyword (approx 200 jobs)

        for page_idx in range(max_pages):
            page_url = f"{url}&start={start_offset}"
            logger.info(
                "LinkedIn: Navigating to page %d (start=%d) for '%s'",
                page_idx + 1,
                start_offset,
                keyword,
            )

            try:
                await page.goto(page_url, timeout=25000, wait_until="domcontentloaded")
            except Exception as goto_err:
                logger.warning(
                    "LinkedIn: Navigation failed for page %d: %s",
                    page_idx + 1,
                    goto_err,
                )
                break

            current_url = page.url
            is_auth_wall = (
                "login" in current_url
                or "checkpoint" in current_url
                or "authwall" in current_url
                or await page.locator("input#username, input#password").count() > 0
                or await page.locator("button.authwall-join-btn").count() > 0
            )

            if is_auth_wall:
                logger.warning(
                    "⚠️ LinkedIn: Login/Authwall detected during pagination traversal!"
                )
                break

            # Wait for main container elements
            try:
                await page.wait_for_selector(
                    "ul.jobs-search__results-list, .scaffold-layout__list, div.base-card, li.scaffold-layout__list-item, a.job-card-list__title--link",
                    timeout=8000,
                )
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

            is_logged_in = (
                await page.locator(
                    ".scaffold-layout__list, li.scaffold-layout__list-item, a.job-card-list__title--link, a.job-card-container__link"
                ).count()
                > 0
            )
            logger.info(
                "LinkedIn: Parsing layout page %d (Logged In: %s)",
                page_idx + 1,
                is_logged_in,
            )

            # Incremental Scrolling List panel (Smart Infinite Scroll)
            try:
                list_panel = page.locator(".scaffold-layout__list")
                if await list_panel.count() > 0:
                    logger.info(
                        "LinkedIn: Scrolling jobs list panel incrementally to load virtualized cards..."
                    )
                    for scroll_step in range(6):
                        await list_panel.evaluate("el => el.scrollTop += 500")
                        await asyncio.sleep(0.8)
            except Exception as scroll_err:
                logger.debug("LinkedIn: Incremental scrolling failed: %s", scroll_err)

            page_jobs = []
            if is_logged_in:
                cards = await page.locator(
                    "li.scaffold-layout__list-item, .job-card-container"
                ).all()
                for card in cards:
                    try:
                        title_el = card.locator(
                            "a.job-card-list__title--link, a.job-card-container__link"
                        ).first
                        if await title_el.count() == 0:
                            continue
                        title = (await title_el.inner_text()).strip()
                        href = await title_el.get_attribute("href")
                        if href and not href.startswith("http"):
                            href = "https://www.linkedin.com" + href
                        url_clean = href.split("?")[0] if href else ""
                        if not url_clean:
                            continue

                        company_el = card.locator(
                            ".job-card-container__primary-description, .artdeco-entity-lockup__subtitle, .job-card-container__company-name"
                        ).first
                        company = (
                            (await company_el.inner_text()).strip()
                            if await company_el.count() > 0
                            else "Unknown"
                        )

                        location_el = card.locator(
                            "li.job-card-container__metadata-item, .job-card-container__metadata-item"
                        ).first
                        loc = (
                            (await location_el.inner_text()).strip()
                            if await location_el.count() > 0
                            else location
                        )

                        posted_el = card.locator(
                            "time, .job-card-container__listed-time"
                        ).first
                        posted_date = (
                            (await posted_el.inner_text()).strip()
                            if await posted_el.count() > 0
                            else ""
                        )

                        page_jobs.append(
                            Job(
                                title=title,
                                company=company,
                                location=loc,
                                experience="0-2 years (Entry Level / Internship)",
                                salary="Not disclosed",
                                url=url_clean,
                                source=self.SOURCE,
                                description=f"Job posting for {title} at {company} in {loc}",
                                requirements="",
                                skills="",
                                posted_date=posted_date,
                                discovered_date=datetime.now(timezone.utc).isoformat(),
                            )
                        )
                    except Exception as card_err:
                        logger.debug("LinkedIn: card parse error: %s", card_err)
            else:
                cards = await page.locator(
                    "div.base-card, li div.base-search-card"
                ).all()
                for card in cards:
                    try:
                        title_el = card.locator(
                            "h3.base-search-card__title, a.base-card__full-link"
                        ).first
                        if await title_el.count() == 0:
                            continue
                        title = (await title_el.inner_text()).strip()

                        link_el = card.locator(
                            "a.base-card__full-link, a.base-search-card__title-link"
                        ).first
                        href = await link_el.get_attribute("href")
                        url_clean = href.split("?")[0] if href else ""
                        if not url_clean:
                            continue

                        company_el = card.locator(
                            "h4.base-search-card__subtitle, a.hidden-nested-link"
                        ).first
                        company = (
                            (await company_el.inner_text()).strip()
                            if await company_el.count() > 0
                            else "Unknown"
                        )

                        location_el = card.locator(
                            "span.job-search-card__location"
                        ).first
                        loc = (
                            (await location_el.inner_text()).strip()
                            if await location_el.count() > 0
                            else location
                        )

                        posted_el = card.locator(
                            "time, span.job-search-card__listdate"
                        ).first
                        posted_date = (
                            (
                                await posted_el.get_attribute("datetime")
                                or await posted_el.inner_text()
                            ).strip()
                            if await posted_el.count() > 0
                            else ""
                        )

                        page_jobs.append(
                            Job(
                                title=title,
                                company=company,
                                location=loc,
                                experience="0-2 years (Entry Level / Internship)",
                                salary="Not disclosed",
                                url=url_clean,
                                source=self.SOURCE,
                                description=f"Job posting for {title} at {company} in {loc}",
                                requirements="",
                                skills="",
                                posted_date=posted_date,
                                discovered_date=datetime.now(timezone.utc).isoformat(),
                            )
                        )
                    except Exception as card_err:
                        logger.debug("LinkedIn: public card parse error: %s", card_err)

            if not page_jobs:
                logger.info(
                    "LinkedIn: No job cards found on page %d. Stopping pagination.",
                    page_idx + 1,
                )
                break

            new_jobs_added = 0
            for pj in page_jobs:
                if pj.url not in [j.url for j in jobs]:
                    jobs.append(pj)
                    new_jobs_added += 1

            logger.info(
                "LinkedIn: Found %d jobs on page %d (%d new)",
                len(page_jobs),
                page_idx + 1,
                new_jobs_added,
            )
            if new_jobs_added == 0:
                logger.info(
                    "LinkedIn: No new jobs added from page %d. Traversal complete.",
                    page_idx + 1,
                )
                break

            start_offset += 25
            await asyncio.sleep(2.0)

        logger.info(
            "LinkedIn: Deterministic search traversal found %d jobs in total", len(jobs)
        )
        return jobs
