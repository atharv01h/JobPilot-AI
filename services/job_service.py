"""
Job service — orchestrates scraping, deduplication, storage, and exports.

V9 CRITICAL FIX:
  - Scrapers now use ScraperContextManager — a FULLY ISOLATED dedicated headless
    Chromium context — NEVER the shared Brave BrowserPool.
  - This eliminates the 'BrowserContext.new_page: Target page, context or browser
    has been closed' crash that occurred when any one scraper tab failure corrupted
    the shared Brave context for all other concurrent scrapers.
  - The shared Brave pool is 100% exclusive to SmartAIOrchestrator agent tasks.
  - Concurrency is capped with asyncio.Semaphore(SCRAPER_CONCURRENCY).
"""

from __future__ import annotations

import asyncio
import typing
from collections.abc import Callable

from config.constants import (
    SCRAPER_CONCURRENCY,
    TARGET_JOBS_PER_SEARCH,
    is_experience_suitable,
)
from config.settings import get_settings
from core.database import get_database
from core.logger import get_logger
from core.models import AppliedJob, Job, SavedJob
from services.notification_service import get_notification_service

logger = get_logger(__name__)


class JobService:
    """High-level job management operations."""

    def __init__(self) -> None:
        self.db = get_database()
        self.notify = get_notification_service()
        self.on_stats_updated: list[Callable[[], None]] = []
        self._search_lock = asyncio.Lock()
        self._is_searching = False

    # ── Search ────────────────────────────────────────────────────────────────

    async def search_jobs(
        self,
        keywords: list[str] | None = None,
        locations: list[str] | None = None,
        sources: list[str] | None = None,
        experience_filters: list[str] | None = None,
        progress_callback: Callable[[str], None] | None = None,
        job_category: str | None = None,
        job_type: str | None = None,
        work_mode: str | None = None,
        country: str | None = None,
        salary_range: str | None = None,
        preferred_companies: list[str] | None = None,
        blacklist_companies: list[str] | None = None,
    ) -> list[Job]:
        """
        Run scrapers in priority tiers concurrently.

        Uses a dedicated HEADLESS CHROMIUM context for all Playwright scraping
        — Brave is reserved for the Browser-Use AI agent only.

        Falls back to the Browser-Use LLM agent if Playwright scraping returns
        no results for a given source/keyword/location combo.
        """
        import time

        from services.session_manager import get_session_manager
        from services.state_manager import AppState, get_state_manager

        # Acquire lock to prevent concurrent searches
        async with self._search_lock:
            if self._is_searching:
                logger.warning(
                    "JobService: search already in progress. Ignoring request."
                )
                return await self.db.get_all_jobs()
            self._is_searching = True

        stm = get_state_manager()
        stm.update_state(app_state=AppState.SEARCHING, is_searching=True)

        sm = get_session_manager()
        sm.is_search_running = True

        settings = get_settings()
        kw_list = keywords or settings.keywords
        loc_list = locations or settings.locations
        src_list = sources or settings.job_sources

        # Priority search tiers
        TIERS = [
            ["linkedin", "naukri"],  # Tier 1
            ["indeed", "foundit"],  # Tier 2
            ["glassdoor"],  # Tier 3
        ]

        new_count = 0
        new_jobs_list: list[Job] = []
        stop_search = False
        _sem = asyncio.Semaphore(SCRAPER_CONCURRENCY)

        def progress(msg: str) -> None:
            logger.info(msg)
            if progress_callback:
                progress_callback(msg)

        progress(
            f"Starting Priority Search: {len(kw_list)} keywords × {len(loc_list)} locations"
        )

        async def scrape_single(
            source: str, keyword: str, location: str, scraper_ctx
        ) -> list[Job]:
            """Scrape one source/keyword/location combo using isolated headless Chromium."""
            nonlocal stop_search

            async with _sem:  # cap concurrency
                if stop_search:
                    return []

                start_t = time.time()
                retry_count = 0
                jobs: list[Job] = []

                # Build scraper
                source_lower = source.lower()
                scraper: typing.Any
                if source_lower == "linkedin":
                    from scrapers.linkedin_scraper import LinkedInScraper

                    scraper = LinkedInScraper()
                elif source_lower == "naukri":
                    from scrapers.naukri_scraper import NaukriScraper

                    scraper = NaukriScraper()
                elif source_lower == "indeed":
                    from scrapers.indeed_scraper import IndeedScraper

                    scraper = IndeedScraper()
                elif source_lower == "foundit":
                    from scrapers.foundit_scraper import FounditScraper

                    scraper = FounditScraper()
                elif source_lower == "glassdoor":
                    from scrapers.glassdoor_scraper import GlassdoorScraper

                    scraper = GlassdoorScraper()
                else:
                    return []

                page = None
                try:
                    # ── Attempt 1: Playwright deterministic scrape ────────────
                    # acquire_page uses the ISOLATED scraper context, never Brave
                    page = await scraper_ctx.acquire_page()
                    try:
                        jobs = await scraper.scrape_playwright(page, keyword, location)
                    except Exception as exc:
                        logger.warning(
                            "Playwright scrape failed (%s): %s — retrying.", source, exc
                        )

                    # ── Attempt 2: Playwright retry ───────────────────────────
                    if not jobs:
                        retry_count += 1
                        try:
                            jobs = await scraper.scrape_playwright(
                                page, keyword, location
                            )
                        except Exception as exc:
                            logger.warning(
                                "Playwright retry failed (%s): %s", source, exc
                            )

                except Exception as exc:
                    logger.error("General scraper exception (%s): %s", source, exc)
                finally:
                    if page:
                        await scraper_ctx.release_page(page)

                duration = time.time() - start_t
                logger.info(
                    "Scrape timing: source=%s kw=%s loc=%s dur=%.2fs jobs=%d retries=%d",
                    source,
                    keyword,
                    location,
                    duration,
                    len(jobs),
                    retry_count,
                )
                return jobs

        # V9: Use isolated ScraperContextManager — never the shared Brave pool
        from automation.scraper_context import ScraperContextManager
        from config.constants import SCRAPER_CONTEXT_TIMEOUT

        try:
            async with ScraperContextManager(
                timeout_ms=SCRAPER_CONTEXT_TIMEOUT
            ) as scraper_ctx:
                for tier_idx, tier_all in enumerate(TIERS):
                    if stop_search:
                        break

                    tier_sources = [
                        s
                        for s in tier_all
                        if s.lower() in [x.lower() for x in src_list]
                    ]
                    if not tier_sources:
                        continue

                    progress(f"Tier {tier_idx + 1}: {', '.join(tier_sources)}")

                    for keyword in kw_list:
                        if stop_search:
                            break
                        for location in loc_list:
                            if stop_search:
                                break

                            progress(f"Searching: '{keyword}' in '{location}'…")

                            tier_tasks = [
                                scrape_single(source, keyword, location, scraper_ctx)
                                for source in tier_sources
                            ]
                            results = await asyncio.gather(
                                *tier_tasks, return_exceptions=True
                            )

                            found: list[Job] = []
                            for res in results:
                                if isinstance(res, list):
                                    found.extend(res)
                                elif isinstance(res, Exception):
                                    logger.error("Scraper task raised: %s", res)

                            suitable = []
                            for j in found:
                                if not is_experience_suitable(j.experience):
                                    continue

                                comp_lower = j.company.lower() if j.company else ""
                                if blacklist_companies:
                                    if any(
                                        bl.lower() in comp_lower
                                        for bl in blacklist_companies
                                        if bl.strip()
                                    ):
                                        logger.info(
                                            "Blacklisted company skipped: %s", j.company
                                        )
                                        continue

                                if work_mode and work_mode != "All":
                                    loc_lower = j.location.lower() if j.location else ""
                                    desc_lower = (
                                        j.description.lower() if j.description else ""
                                    )
                                    if (
                                        work_mode == "Remote"
                                        and "remote" not in loc_lower
                                        and "remote" not in desc_lower
                                    ) or (
                                        work_mode == "Hybrid"
                                        and "hybrid" not in loc_lower
                                        and "hybrid" not in desc_lower
                                    ) or work_mode == "Onsite" and (
                                        "remote" in loc_lower or "hybrid" in loc_lower
                                    ):
                                        continue

                                if job_type and job_type != "All":
                                    type_lower = (
                                        j.description.lower() if j.description else ""
                                    )
                                    title_lower = j.title.lower() if j.title else ""
                                    if (
                                        job_type.lower() == "internship"
                                        and "intern" not in title_lower
                                        and "intern" not in type_lower
                                    ) or (
                                        job_type.lower() == "contract"
                                        and "contract" not in type_lower
                                    ):
                                        continue

                                suitable.append(j)

                            for job in suitable:
                                if await self.db.is_duplicate(
                                    job.url, job.company, job.title
                                ):
                                    logger.debug(
                                        "Duplicate skipped: %s @ %s",
                                        job.title,
                                        job.company,
                                    )
                                    continue
                                job_id = await self.db.insert_job(job)
                                if job_id:
                                    job.id = job_id
                                    new_jobs_list.append(job)
                                    new_count += 1
                                    if new_count >= TARGET_JOBS_PER_SEARCH:
                                        progress(
                                            f"Target of {TARGET_JOBS_PER_SEARCH} jobs reached — stopping."
                                        )
                                        stop_search = True
                                        break

                            progress(f"  → {new_count} new unique jobs so far.")

            # Log search history
            await self.db.log_search(kw_list, loc_list, src_list, new_count)

            if new_count > 0:
                self.notify.notify_jobs_found(new_count, ", ".join(src_list))
                for cb in self.on_stats_updated:
                    try:
                        cb()
                    except Exception as _exc:
                        logger.debug("Suppressed: %s", _exc)

                try:
                    from services.queue_manager import get_job_queue_manager

                    new_jobs_ranked = self.rank_and_prioritize_jobs(
                        new_jobs_list, preferred_companies
                    )
                    logger.info(
                        "JobService: Automatically enqueuing %d new jobs to JobQueueManager",
                        len(new_jobs_ranked),
                    )
                    await get_job_queue_manager().enqueue_jobs(new_jobs_ranked)
                except Exception as q_err:
                    logger.error("JobService: Failed to enqueue new jobs: %s", q_err)

            return await self.db.get_all_jobs()

        finally:
            self._is_searching = False
            sm.is_search_running = False

            # Determine next StateManager app state
            from services.queue_manager import get_application_queue
            from services.state_manager import AppState, get_state_manager

            stm = get_state_manager()
            try:
                q = get_application_queue()
                if q._paused:
                    next_state = AppState.PAUSED
                elif q._is_processing:
                    next_state = AppState.APPLYING
                elif await q.size() > 0:
                    next_state = AppState.QUEUED
                else:
                    next_state = AppState.IDLE
            except Exception:
                next_state = AppState.IDLE
            stm.update_state(app_state=next_state, is_searching=False)

    def rank_and_prioritize_jobs(
        self, jobs: list[Job], preferred_companies: list[str] | None = None
    ) -> list[Job]:
        """
        Rank jobs based on multiple prioritization factors:
        - Easy Apply (marked in description or title)
        - Preferred Companies match
        - Remote / Preferred Locations
        - Recency indicators
        Returns the sorted list of jobs (highest priority first).
        """
        if not jobs:
            return []

        pref_comps = (
            [c.lower().strip() for c in preferred_companies]
            if preferred_companies
            else []
        )

        def calculate_score(job: Job) -> float:
            score = 0.0
            desc_lower = job.description.lower() if job.description else ""
            title_lower = job.title.lower() if job.title else ""
            loc_lower = job.location.lower() if job.location else ""

            # 1. Easy Apply Priority
            if (
                "easy apply" in desc_lower
                or "apply without resume" in desc_lower
                or "quick apply" in desc_lower
            ):
                score += 5.0

            # 2. Preferred Companies match
            comp_lower = job.company.lower() if job.company else ""
            if comp_lower and pref_comps:
                if any(pc in comp_lower for pc in pref_comps if pc):
                    score += 4.0

            # 3. Remote / Preferred Locations
            if "remote" in loc_lower or "remote" in desc_lower:
                score += 3.0

            # 4. Recent Jobs indicators
            if any(
                rec in desc_lower or rec in title_lower
                for rec in ["today", "just posted", "1 day ago", "active"]
            ):
                score += 2.0

            # 5. Higher Salary indicator
            if (
                "$" in job.salary
                or "₹" in job.salary
                or "salary" in desc_lower
                or "lpa" in job.salary.lower()
            ):
                score += 1.0

            return score

        return sorted(jobs, key=calculate_score, reverse=True)

    # ── CRUD ──────────────────────────────────────────────────────────────────

    async def get_all_jobs(self, status_filter: str | None = None) -> list[Job]:
        return await self.db.get_all_jobs(status_filter)

    async def get_job(self, job_id: int) -> Job | None:
        return await self.db.get_job_by_id(job_id)

    async def save_job(self, job_id: int) -> bool:
        result = await self.db.save_job(job_id)
        if result:
            logger.info("Job %d saved.", job_id)
            for cb in self.on_stats_updated:
                try:
                    cb()
                except Exception as _exc:
                    logger.debug("Suppressed: %s", _exc)
            return True
        return False

    async def mark_applied(
        self, job_id: int, application_url: str = "", notes: str = ""
    ) -> bool:
        result = await self.db.mark_applied(job_id, application_url, notes)
        if result:
            job = await self.db.get_job_by_id(job_id)
            if job:
                self.notify.notify_applied(job.title, job.company)
            logger.info("Job %d marked as applied.", job_id)
            for cb in self.on_stats_updated:
                try:
                    cb()
                except Exception as _exc:
                    logger.debug("Suppressed: %s", _exc)
            return True
        return False

    async def get_saved_jobs(self) -> list[SavedJob]:
        return await self.db.get_saved_jobs()

    async def get_applied_jobs(self) -> list[AppliedJob]:
        return await self.db.get_applied_jobs()

    # ── Stats ─────────────────────────────────────────────────────────────────

    async def get_stats(self) -> dict:
        return {
            "total_jobs": await self.db.get_jobs_count(),
            "saved_jobs": await self.db.get_saved_jobs_count(),
            "applied_jobs": await self.db.get_applied_jobs_count(),
            "today_found": await self.db.get_today_count(),
        }

    # ── Export ────────────────────────────────────────────────────────────────

    async def export_csv(self) -> tuple[str, str]:
        jobs_csv = await self.db.export_jobs_csv()
        applied_csv = await self.db.export_applied_csv()
        return jobs_csv, applied_csv


# ── Singleton ─────────────────────────────────────────────────────────────────

_job_service: JobService | None = None


def get_job_service() -> JobService:
    global _job_service
    if _job_service is None:
        _job_service = JobService()
    return _job_service
