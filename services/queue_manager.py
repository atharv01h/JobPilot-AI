"""
Queue manager — orchestrates JobQueueManager and ApplicationQueue for deterministic sequential processing.

V10: Handles all FailureReason enum values.
Queue NEVER stops regardless of individual application failure type.
"""

from __future__ import annotations

import asyncio

from core.logger import get_logger
from core.models import Job

logger = get_logger(__name__)

# All result values that represent a completed (possibly failed) application
# The queue moves on after any of these — nothing stops the queue.
_TERMINAL_RESULTS = {
    # Success
    "SUCCESS",
    "APPLICATION_SUBMITTED",
    "APPLICATION_COMPLETED",
    # Skipped / failed — map to appropriate DB status
    "UPLOAD_FAILED",
    "ACCOUNT_REQUIRED",
    "LOGIN_REQUIRED",
    "REDIRECTED_TO_COMPANY",
    "CAPTCHA_BLOCKED",
    "OTP_REQUIRED",
    "EMAIL_VERIFICATION_REQUIRED",
    "UNSUPPORTED_SITE",
    "APPLICATION_CLOSED",
    "FORM_LOOP",
    "AI_FAILURE",
    "NETWORK_ERROR",
    "TIMEOUT",
    "APPLICATION_FAILED",
    "APPLICATION_SKIPPED",
    "EXTERNAL_APPLICATION_REQUIRED",
    "UNKNOWN",
    "FORM_FILL_FAILED",  # New: form filling failed
    "INELIGIBLE",  # New: experience/criteria not met
}

_SUCCESS_RESULTS = {"SUCCESS", "APPLICATION_SUBMITTED", "APPLICATION_COMPLETED"}

# Non-retryable failures - these should not be retried automatically
_NON_RETRYABLE_RESULTS = {
    "ACCOUNT_REQUIRED",
    "LOGIN_REQUIRED",
    "CAPTCHA_BLOCKED",
    "OTP_REQUIRED",
    "EMAIL_VERIFICATION_REQUIRED",
    "UNSUPPORTED_SITE",
    "APPLICATION_CLOSED",
    "EXTERNAL_APPLICATION_REQUIRED",
    "INELIGIBLE",
    "UNKNOWN",  # Unknown errors - treat as non-retryable
    "APPLICATION_SKIPPED",  # Explicitly skipped
}

# Retryable failures - can be retried later
_RETRYABLE_RESULTS = {
    "UPLOAD_FAILED",
    "REDIRECTED_TO_COMPANY",
    "FORM_LOOP",
    "AI_FAILURE",
    "NETWORK_ERROR",
    "TIMEOUT",
    "APPLICATION_FAILED",
    "FORM_FILL_FAILED",
}


class ApplicationQueue:
    """Manages the persistent database-backed queue of jobs and executes them sequentially."""

    def __init__(self) -> None:
        self._is_processing: bool = False
        self._paused: bool = False
        self._active_task: asyncio.Task | None = None
        self._current_job: Job | None = None
        self.on_queue_updated: list[Callable[[], None]] = []

    def register_callback(self, cb: Callable[[], None]) -> None:
        if cb not in self.on_queue_updated:
            self.on_queue_updated.append(cb)

    def trigger_update(self) -> None:
        for cb in self.on_queue_updated:
            try:
                cb()
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

    async def enqueue(self, job: Job, priority: int = 0) -> None:
        from datetime import datetime, timezone

        from core.database import get_database

        db = get_database()
        await db.add_to_queue(job.id, priority, datetime.now(timezone.utc).isoformat())
        logger.info(
            "ApplicationQueue: Enqueued job: %s @ %s (priority=%d)",
            job.title,
            job.company,
            priority,
        )
        self.trigger_update()

        from services.state_manager import AppState, get_state_manager

        stm = get_state_manager()
        if stm.app_state in (AppState.IDLE, AppState.COMPLETED, AppState.FAILED):
            stm.update_state(app_state=AppState.QUEUED)

        if not self._is_processing and not self._paused:
            await self.start_processing()

    async def size(self) -> int:
        from core.database import get_database

        db = get_database()
        return await db.get_queue_size()

    async def get_queue_items(self) -> list[dict]:
        """Return all queue items with job details."""
        from core.database import get_database

        db = get_database()
        return await db.get_queue_items()

    async def start_processing(self) -> None:
        if self._is_processing:
            return
        self._is_processing = True
        self._paused = False
        self._active_task = asyncio.create_task(self._process_loop())
        logger.info("ApplicationQueue: Started background application queue processor.")
        self.trigger_update()
        from services.state_manager import AppState, get_state_manager

        get_state_manager().update_state(app_state=AppState.APPLYING)

    async def stop_processing(self) -> None:
        self._is_processing = False
        if self._active_task:
            self._active_task.cancel()
            try:
                await self._active_task
            except asyncio.CancelledError:
                pass
            self._active_task = None
        logger.info("ApplicationQueue: Stopped background application queue processor.")
        self.trigger_update()
        from services.state_manager import AppState, get_state_manager

        size = await self.size()
        next_state = AppState.QUEUED if size > 0 else AppState.IDLE
        get_state_manager().update_state(
            app_state=next_state,
            current_job=None,
            current_website="Unavailable",
            current_ats="Unavailable",
        )

    def pause(self) -> None:
        self._paused = True
        logger.info("ApplicationQueue: Paused.")
        self.trigger_update()
        from services.state_manager import AppState, get_state_manager

        get_state_manager().update_state(app_state=AppState.PAUSED)

    async def resume(self) -> None:
        self._paused = False
        logger.info("ApplicationQueue: Resumed.")
        self.trigger_update()
        from services.state_manager import AppState, get_state_manager

        if not self._is_processing:
            await self.start_processing()
        else:
            get_state_manager().update_state(app_state=AppState.APPLYING)

    async def cancel_current(self) -> None:
        if self._current_job:
            logger.info(
                "ApplicationQueue: Cancelling current job application: %s",
                self._current_job.title,
            )
            if self._active_task:
                self._active_task.cancel()
                self._active_task = None

            from core.database import get_database
            from core.models import JobStatus

            db = get_database()
            await db.update_queue_item_status(self._current_job.id, "FAILED")
            await db.update_job_status(self._current_job.id, JobStatus.FAILED)
            await db.add_application_attempt(
                self._current_job.id, JobStatus.FAILED, "Cancelled by user"
            )

            self._current_job = None
            self._is_processing = False
            self.trigger_update()
            from services.state_manager import get_state_manager

            get_state_manager().update_state(
                current_job=None,
                current_website="Unavailable",
                current_ats="Unavailable",
            )
            await self.resume()

    async def clear_completed(self) -> None:
        from core.database import get_database

        db = get_database()
        await db.clear_completed_queue()
        logger.info("ApplicationQueue: Cleared completed items.")
        self.trigger_update()

    async def clear_queue(self) -> None:
        from core.database import get_database

        db = get_database()
        await db.clear_all_queue()
        logger.info("ApplicationQueue: Cleared all queue items.")
        self.trigger_update()

    async def clear_failed(self) -> None:
        from core.database import get_database

        db = get_database()
        await db.clear_failed_queue()
        logger.info("ApplicationQueue: Cleared failed items.")
        self.trigger_update()

    async def retry_failed(self) -> None:
        from core.database import get_database

        db = get_database()
        await db.retry_failed_queue()
        logger.info("ApplicationQueue: Resubmitted failed queue items to PENDING.")
        self.trigger_update()
        if not self._is_processing and not self._paused:
            await self.start_processing()

    async def retry_selected(self, job_ids: list[int]) -> None:
        from core.database import get_database

        db = get_database()
        await db.retry_selected_queue(job_ids)
        logger.info("ApplicationQueue: Resubmitted selected queue items to PENDING.")
        self.trigger_update()
        if not self._is_processing and not self._paused:
            await self.start_processing()

    async def retry_external(self) -> None:
        from datetime import datetime, timezone

        from core.database import get_database

        db = get_database()
        await db.retry_external_jobs(datetime.now(timezone.utc).isoformat())
        logger.info(
            "ApplicationQueue: Enqueued all external/redirected jobs for retry."
        )
        self.trigger_update()
        if not self._is_processing and not self._paused:
            await self.start_processing()

    async def retry_retryable(self) -> None:
        """Retry only failures that are potentially retryable (network errors, timeouts, etc.)."""
        from core.database import get_database

        db = get_database()
        await db.retry_retryable_failures(_RETRYABLE_RESULTS)
        logger.info("ApplicationQueue: Resubmitted retryable failures to PENDING.")
        self.trigger_update()
        if not self._is_processing and not self._paused:
            await self.start_processing()

    async def apply_selected(self, job_ids: list[int]) -> None:
        from datetime import datetime, timezone

        from core.database import get_database

        db = get_database()
        await db.apply_selected_jobs_queue(job_ids, datetime.now(timezone.utc).isoformat())
        logger.info("ApplicationQueue: Enqueued selected jobs: %s", job_ids)
        self.trigger_update()
        if not self._is_processing and not self._paused:
            await self.start_processing()

    async def apply_all(self) -> None:
        from datetime import datetime, timezone

        from core.database import get_database

        db = get_database()
        await db.apply_all_new_jobs_queue(datetime.now(timezone.utc).isoformat())
        logger.info("ApplicationQueue: Enqueued all NEW jobs.")
        self.trigger_update()
        if not self._is_processing and not self._paused:
            await self.start_processing()

    async def update_priority(self, job_id: int, priority: int) -> None:
        from core.database import get_database

        db = get_database()
        await db.update_queue_priority(job_id, priority)
        logger.info(
            "ApplicationQueue: Updated priority for job %d to %d", job_id, priority
        )
        self.trigger_update()

    async def _process_loop(self) -> None:
        from automation.browser_manager import get_browser_manager
        from core.database import get_database

        db = get_database()

        while self._is_processing:
            if self._paused:
                await asyncio.sleep(1.0)
                continue

            job = await db.get_next_pending_queue_item()

            if not job:
                await asyncio.sleep(2.0)
                continue

            self._current_job = job
            self.trigger_update()

            # Update StateManager
            from urllib.parse import urlparse

            from services.state_manager import AppState, get_state_manager

            stm = get_state_manager()
            domain = urlparse(job.url).netloc or "generic"
            url_l = job.url.lower()
            ats = "Generic"
            if "workday" in url_l:
                ats = "Workday"
            elif "successfactors" in url_l:
                ats = "SuccessFactors"
            elif "greenhouse" in url_l:
                ats = "Greenhouse"
            elif "lever" in url_l:
                ats = "Lever"
            elif "taleo" in url_l:
                ats = "Taleo"

            stm.update_state(
                app_state=AppState.APPLYING,
                current_job=job,
                current_website=domain,
                current_ats=ats,
            )

            logger.info(
                "ApplicationQueue: [START] Processing application for: %s @ %s (%s)",
                job.title,
                job.company,
                job.url,
            )

            result = "ERROR"
            try:
                browser_mgr = get_browser_manager()
                result = await browser_mgr.run_job_application(job)
                logger.info(
                    "ApplicationQueue: [RESULT] Application finished for job '%s': %s",
                    job.title,
                    result,
                )
            except asyncio.CancelledError:
                logger.info(
                    "ApplicationQueue: Task cancelled while processing job '%s'.",
                    job.title,
                )
                raise
            except Exception as e:
                logger.error(
                    "ApplicationQueue: Unexpected error applying to job '%s': %s",
                    job.title,
                    e,
                )
                result = "ERROR"

            from core.models import JobStatus

            # Map result to canonical JobStatus
            if result in _SUCCESS_RESULTS:
                canonical_status = JobStatus.SUBMITTED
            elif result in _NON_RETRYABLE_RESULTS:
                canonical_status = (
                    JobStatus.ERROR
                    if result
                    in (
                        "LOGIN_REQUIRED",
                        "ACCOUNT_REQUIRED",
                        "CAPTCHA_BLOCKED",
                        "OTP_REQUIRED",
                        "EMAIL_VERIFICATION_REQUIRED",
                    )
                    else JobStatus.SKIPPED
                )
            elif result in _RETRYABLE_RESULTS:
                canonical_status = JobStatus.FAILED
            elif result in ("REDIRECTED", "REDIRECTED_TO_COMPANY"):
                canonical_status = JobStatus.REDIRECTED
            elif result in ("EXTERNAL_APPLICATION_REQUIRED", "EXTERNAL_REQUIRED"):
                canonical_status = JobStatus.EXTERNAL_REQUIRED
            else:
                canonical_status = JobStatus.ERROR

            await db.update_job_status(job.id, canonical_status)
            await db.add_application_attempt(
                job.id, canonical_status, f"Result code: {result}"
            )

            # Queue status: COMPLETED for success, FAILED for retryable, COMPLETED for non-retryable (they won't be retried)
            if result in _SUCCESS_RESULTS:
                queue_status = "COMPLETED"
            elif result in _NON_RETRYABLE_RESULTS:
                queue_status = "COMPLETED"  # Non-retryable - mark as completed so they don't block queue
            else:
                queue_status = "FAILED"  # Retryable - can be retried later
            await db.update_queue_item_status(job.id, queue_status)

            self._current_job = None
            self.trigger_update()

            # Check if queue has more pending jobs
            size = await self.size()
            next_state = AppState.QUEUED if size > 0 else AppState.COMPLETED

            from services.state_manager import get_state_manager

            get_state_manager().update_state(
                app_state=next_state,
                current_job=None,
                current_website="Unavailable",
                current_ats="Unavailable",
            )
            await asyncio.sleep(2.0)


import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from config.constants import (
    is_experience_suitable,
)
from core.models import JobStatus


def normalize_url(url: str) -> str:
    """
    Normalizes a URL to a canonical format.
    Removes tracking parameters and handles trailing slashes/casing.
    """
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        qparams = parse_qsl(parsed.query)
        # Keep only essential query parameters (e.g. 'jk' for indeed)
        keep_params = {"jk", "id"}
        filtered_qparams = [(k, v) for k, v in qparams if k.lower() in keep_params]
        filtered_qparams.sort()
        normalized_query = urlencode(filtered_qparams)
        path = parsed.path.rstrip("/")
        return urlunparse(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                path,
                parsed.params,
                normalized_query,
                "",
            )
        )
    except Exception:
        return url.strip().lower()


def normalize_title(title: str) -> str:
    """
    Normalizes a job title to compare identical jobs without getting thrown off by subtle differences.
    """
    if not title:
        return ""
    t = title.lower()
    t = re.sub(r"[^\w\s]", "", t)  # remove punctuation
    t = re.sub(r"\s+", " ", t)  # collapse whitespace
    return t.strip()


def normalize_company(company: str) -> str:
    """
    Normalizes a company name to compare identical companies.
    """
    if not company:
        return ""
    c = company.lower()
    c = re.sub(r"[^\w\s]", "", c)  # remove punctuation
    c = re.sub(r"\s+", " ", c)  # collapse whitespace
    return c.strip()


class JobQueueManager:
    """Manages the job queue lifecycle: receives, validates, deduplicates, and enqueues jobs."""

    def __init__(self, app_queue: ApplicationQueue) -> None:
        self.app_queue = app_queue

    def _log_rejection(self, job: Job, rule: str, reason: str, result: str) -> None:
        logger.warning(
            "\n=========================================\n"
            "Job Queue Rejection Audit:\n"
            "Rejected\n"
            "Reason: %s\n"
            "Job Title: %s\n"
            "Company: %s\n"
            "URL: %s\n"
            "Validation Rule: %s\n"
            "Validation Result: %s\n"
            "=========================================",
            reason,
            job.title or "(None)",
            job.company or "(None)",
            job.url or "(None)",
            rule,
            result,
        )

    async def enqueue_jobs(self, jobs: list[Job]) -> None:
        """
        Deduplicates, validates, and enqueues job objects to the ApplicationQueue.
        """
        from core.database import get_database

        db = get_database()

        jobs_scraped = len(jobs)
        jobs_validated = 0
        jobs_rejected = 0
        jobs_duplicated = 0
        jobs_queued = 0

        # Load all existing database jobs to check for duplicates
        all_db_jobs = await db.get_all_jobs()

        # Keep track of jobs enqueued in the current batch to prevent duplicates in the same batch
        enqueued_urls = set()
        enqueued_keys = set()  # (website, normalized_title, normalized_company)

        for job in jobs:
            try:
                # 1. Validation
                if not job.title or not job.title.strip():
                    self._log_rejection(
                        job, "Title Presence", "Missing Title", "Fail: Title is empty"
                    )
                    jobs_rejected += 1
                    continue
                if not job.company or not job.company.strip():
                    self._log_rejection(
                        job,
                        "Company Presence",
                        "Missing Company",
                        "Fail: Company is empty",
                    )
                    jobs_rejected += 1
                    continue
                if not job.url or not job.url.strip():
                    self._log_rejection(
                        job, "URL Presence", "Missing URL", "Fail: URL is empty"
                    )
                    jobs_rejected += 1
                    continue

                # Check / recover website (source)
                source = job.source.lower().strip() if job.source else ""
                if not source:
                    # Attempt recovery from URL
                    url_lower = job.url.lower()
                    for site in [
                        "linkedin",
                        "naukri",
                        "indeed",
                        "foundit",
                        "glassdoor",
                        "wellfound",
                        "instahyre",
                    ]:
                        if site in url_lower:
                            source = site
                            job.source = site
                            break

                if not source or source not in [
                    "linkedin",
                    "naukri",
                    "indeed",
                    "foundit",
                    "glassdoor",
                    "wellfound",
                    "instahyre",
                ]:
                    self._log_rejection(
                        job,
                        "Website Support",
                        "Unsupported website",
                        f"Fail: Website '{job.source}' is unsupported",
                    )
                    jobs_rejected += 1
                    continue

                # Experience validation
                if not is_experience_suitable(job.experience):
                    self._log_rejection(
                        job,
                        "Experience Suitability",
                        "Experience exceeds limit",
                        f"Fail: Experience '{job.experience}' exceeds threshold",
                    )
                    jobs_rejected += 1
                    continue

                # The job passes basic validation rules
                jobs_validated += 1

                # 2. Deduplication check
                cand_norm_url = normalize_url(job.url)
                cand_norm_title = normalize_title(job.title)
                cand_norm_company = normalize_company(job.company)
                cand_site = source
                cand_key = (cand_site, cand_norm_title, cand_norm_company)

                # Check if it was already processed in the current batch
                if cand_norm_url in enqueued_urls or cand_key in enqueued_keys:
                    self._log_rejection(
                        job,
                        "Batch Deduplication",
                        "Duplicate database entry",
                        "Fail: Already enqueued in current batch",
                    )
                    jobs_duplicated += 1
                    continue

                # Check against database jobs
                is_duplicate_db = False
                db_already_applied = False
                existing_db_job = None

                for db_job in all_db_jobs:
                    # Match by job.id
                    if job.id and db_job.id == job.id:
                        existing_db_job = db_job
                        break
                    # Match by URL
                    if db_job.url and normalize_url(db_job.url) == cand_norm_url:
                        existing_db_job = db_job
                        break
                    # Match by Title + Company + Website
                    if (
                        db_job.source
                        and db_job.source.lower().strip() == cand_site
                        and normalize_title(db_job.title) == cand_norm_title
                        and normalize_company(db_job.company) == cand_norm_company
                    ):
                        existing_db_job = db_job
                        break

                if existing_db_job:
                    # We found a matching database job. Check if it's already applied to.
                    if existing_db_job.status in (
                        JobStatus.APPLIED,
                        JobStatus.SUBMITTED,
                    ):
                        db_already_applied = True
                        is_duplicate_db = True
                    else:
                        # Existing job in DB but NOT applied yet (e.g. 'new' or 'saved').
                        # We do NOT reject it! We reuse its database details.
                        job.id = existing_db_job.id
                        job.status = existing_db_job.status
                else:
                    # Completely new job. Insert it.
                    job_id = await db.insert_job(job)
                    if job_id:
                        job.id = job_id
                    else:
                        # Insert OR IGNORE failed/skipped, meaning a unique constraint was triggered, i.e. duplicate URL
                        is_duplicate_db = True

                if is_duplicate_db:
                    if db_already_applied:
                        self._log_rejection(
                            job,
                            "Database Deduplication",
                            "Already applied",
                            "Fail: Already applied to this job in DB",
                        )
                    else:
                        self._log_rejection(
                            job,
                            "Database Deduplication",
                            "Duplicate database entry",
                            "Fail: Duplicate database entry exists",
                        )
                    jobs_duplicated += 1
                    continue

                # Add to current batch cache
                enqueued_urls.add(cand_norm_url)
                enqueued_keys.add(cand_key)

                # Enqueue to ApplicationQueue
                await self.app_queue.enqueue(job)
                jobs_queued += 1

            except Exception as e:
                self._log_rejection(
                    job,
                    "General Processing",
                    "Malformed data",
                    f"Fail: Exception raised during validation: {e}",
                )
                jobs_rejected += 1
                continue

        jobs_remaining = await self.app_queue.size()

        logger.info(
            "\n=========================================\n"
            "Queue Diagnostics:\n"
            "Jobs Scraped: %d\n"
            "Jobs Validated: %d\n"
            "Jobs Rejected: %d\n"
            "Jobs Duplicated: %d\n"
            "Jobs Queued: %d\n"
            "Jobs Remaining: %d\n"
            "=========================================",
            jobs_scraped,
            jobs_validated,
            jobs_rejected,
            jobs_duplicated,
            jobs_queued,
            jobs_remaining,
        )

        if jobs_queued == 0:
            if jobs_scraped == 0:
                logger.info(
                    "Queue Diagnostics: No jobs enqueued because search returned 0 scraped jobs."
                )
            elif jobs_rejected + jobs_duplicated == jobs_scraped:
                logger.info(
                    "Queue Diagnostics: No jobs enqueued because all %d scraped jobs were filtered out (Rejected=%d, Duplicated=%d).",
                    jobs_scraped,
                    jobs_rejected,
                    jobs_duplicated,
                )
            else:
                logger.info(
                    "Queue Diagnostics: No jobs enqueued. All scraped jobs were processed or skipped."
                )

        if jobs_queued > 0:
            await self.app_queue.start_processing()


# ── Singletons ────────────────────────────────────────────────────────────────

_app_queue: ApplicationQueue | None = None
_job_queue_manager: JobQueueManager | None = None


def get_application_queue() -> ApplicationQueue:
    global _app_queue
    if _app_queue is None:
        _app_queue = ApplicationQueue()
    return _app_queue


def get_job_queue_manager() -> JobQueueManager:
    global _job_queue_manager
    if _job_queue_manager is None:
        _job_queue_manager = JobQueueManager(get_application_queue())
        try:
            from core.service_registry import ServiceRegistry

            ServiceRegistry.register("Queue", _job_queue_manager)
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)
    return _job_queue_manager
