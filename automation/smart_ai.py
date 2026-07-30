"""
smart_ai.py — Modular AI Orchestration Engine.

Decouples browser-use from architectural decision making.
Hosts:
  - SmartAIOrchestrator: Handles structured task execution by delegating to deterministic website modules.
"""

from __future__ import annotations

import asyncio
import re
import time

from openai import AsyncOpenAI
from playwright.async_api import Page

from automation.browser_health import (
    record_heartbeat,
)
from config.constants import LLM_BASE_URL, LLM_MODEL
from config.settings import get_settings
from core.logger import get_logger
from core.models import Job

logger = get_logger(__name__)


class SmartAIOrchestrator:
    """Orchestrates structured task execution by delegating to deterministic modules."""

    def __init__(self, page: Page) -> None:
        self._page = page
        self._client: AsyncOpenAI | None = None
        self._init_llm_client()
        self.force_abort = False

        self.consecutive_identical_actions = 0
        self.consecutive_identical_planner_outputs = 0
        self.recovery_attempts = 0
        self.job_start_time = time.time()
        self.max_job_duration = (
            300.0  # 5 minutes configurable max execution time per job
        )

    @property
    def page(self) -> Page:
        return self._page

    @page.setter
    def page(self, new_page: Page) -> None:
        logger.info("SmartAIOrchestrator: Updating page reference.")
        self._page = new_page

    def _init_llm_client(self) -> None:
        settings = get_settings()
        api_key = settings.llm_api_key
        if not api_key:
            raise ValueError("LLM_API_KEY is missing. Configure it in Settings.")

        base_url = settings.llm_base_url or LLM_BASE_URL
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = settings.llm_model or LLM_MODEL

    def _detect_site_name(self, url: str | None = None) -> str:
        if not url:
            url = self._page.url
        url = url.lower()
        for site in [
            "linkedin",
            "naukri",
            "indeed",
            "foundit",
            "glassdoor",
            "wellfound",
            "instahyre",
        ]:
            if site in url:
                return site
        return "linkedin"

    def _is_single_job_url(self, url: str) -> bool:
        """Checks if a URL is a specific job description page rather than a homepage or search page."""
        url_lower = url.lower()
        if "/jobs/view" in url_lower or "/viewjob" in url_lower or "jk=" in url_lower:
            return True
        if "/job-listings-" in url_lower or "joblistingid=" in url_lower:
            return True
        if "/job/" in url_lower or "/jobs/" in url_lower:
            path_after_job = (
                url_lower.split("/jobs/")[-1]
                if "/jobs/" in url_lower
                else url_lower.split("/job/")[-1]
            )
            path_after_job = path_after_job.strip("/")
            if path_after_job and path_after_job not in [
                "",
                "search",
                "search/",
                "index.htm",
            ]:
                return True
        if "/opportunities/" in url_lower:
            path = url_lower.split("/opportunities/")[-1].strip("/")
            if path and path not in ["", "search"]:
                return True
        return "/partner/joblisting.htm" in url_lower

    def _parse_task_parameters(self, task_description: str) -> dict:
        """Parses the keyword, location, resume path, and target URL from the task instructions."""
        params = {
            "url": "",
            "keyword": "Software Engineer",
            "location": "Remote",
            "resume_path": "",
            "company": "",
        }

        # 1. Parse Target URL
        m = re.search(r"Target URL:\s*(https?://[^\s]+)", task_description)
        if m:
            params["url"] = m.group(1).strip()

        # 2. Parse Job Title / Keyword and Company
        m = re.search(r"Job:\s*(.*?)\s+at\s+(.*)", task_description)
        if m:
            params["keyword"] = m.group(1).strip()
            params["company"] = m.group(2).strip()

        # 3. Parse Resume Path
        m = re.search(r"Resume Path:\s*(.*)", task_description)
        if m:
            params["resume_path"] = m.group(1).strip()

        # Fallback to resume service if not explicitly passed
        try:
            from services.resume_service import get_resume_service

            r_svc = get_resume_service()
            if not params["resume_path"] and r_svc.path_str:
                params["resume_path"] = r_svc.path_str
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)

        return params

    async def apply_to_job(self, job: Job, resume_path: str, form_data: dict) -> str:
        """
        Runs the application pipeline for a single job using the LLM-First Decision Engine.
        """
        logger.info(
            "SmartAIOrchestrator: Applying to job: %s at %s (URL: %s)",
            job.title,
            job.company,
            job.url,
        )

        try:
            from automation.llm_decision_engine import LLMFirstDecisionEngine

            engine = LLMFirstDecisionEngine(self._page)
            result = await engine.apply_to_job(job, resume_path, form_data)
            return result
        except asyncio.CancelledError:
            logger.warning("SmartAIOrchestrator: Task cancelled by watchdog.")
            raise
        except Exception as exc:
            logger.error(
                "SmartAIOrchestrator: Error running LLMFirstDecisionEngine apply_to_job: %s",
                exc,
            )
            return "FAILED"

    async def run_task(self, task_description: str, max_steps: int = 40) -> str:
        """
        Deprecated. Use apply_to_job instead.
        """
        logger.warning(
            "SmartAIOrchestrator: run_task is DEPRECATED and will be removed. Please use apply_to_job."
        )
        params = self._parse_task_parameters(task_description)
        job = Job(
            title=params["keyword"],
            company=params["company"] or "Unknown",
            url=params["url"],
            location=params["location"],
            source=self._detect_site_name(params["url"]),
            experience="",
            salary="",
            description="",
            requirements="",
            skills="",
            posted_date="",
        )
        return await self.apply_to_job(job, params["resume_path"], {})

    async def ask_llm_question(
        self,
        question: str,
        field_type: str,
        placeholder: str = "",
        validation_text: str = "",
        nearby_text: str = "",
        job_desc: str = "",
    ) -> str:
        """
        Uses the LLM strictly to reason and answer custom/ambiguous form questions.
        """
        from services.form_service import get_form_service

        form_summary = ""
        try:
            form_summary = get_form_service().get_form_summary()
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)

        prompt = f"""You are the Recruiter AI Assistant. Answer this custom application form question on behalf of the applicant.
        
        Applicant Profile Information:
        {form_summary}
        
        Job Description:
        {job_desc}
        
        Question/Field Context:
        - Question: {question}
        - Field Type: {field_type}
        - Placeholder: {placeholder}
        - Validation/Error Text: {validation_text}
        - Nearby Page Context: {nearby_text}
        
        Provide a concise, direct, and professional answer suitable for a job application form.
        Return ONLY the text to fill in the field, with no surrounding quotes, markdown, or explanations.
        """

        try:
            record_heartbeat("llm")
            resp = await asyncio.wait_for(
                self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a professional assistant. Answer form questions directly.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                ),
                timeout=12.0,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            logger.error("LLM question query failed: %s", e)
            return ""

    async def trigger_recovery_level(self, level: int) -> None:
        """Watchdog progressive recovery interface."""
        logger.warning(
            "SmartAIOrchestrator: Watchdog triggered Progressive Recovery Level %d...",
            level,
        )
        record_heartbeat("recovery")
        try:
            if level <= 4:
                # Reload current page
                logger.info("Recovery Level %d: Reloading current page.", level)
                await self._page.reload(timeout=15000)
            elif level <= 7:
                # Open fresh tab
                logger.info("Recovery Level %d: Opening fresh tab.", level)
                from automation.browser_session_pool import get_browser_session_pool

                pool = get_browser_session_pool()
                try:
                    await self._page.close()
                except Exception as _exc:
                    logger.debug("Suppressed: %s", _exc)
                async with pool.page() as new_page:
                    self.page = new_page
            elif level <= 10:
                # Restart browser and context
                logger.info("Recovery Level %d: Restarting browser context.", level)
                from automation.browser_session_pool import get_browser_session_pool

                pool = get_browser_session_pool()
                await pool.close()
                await pool.reconnect()
                async with pool.context() as ctx:
                    self.page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            else:
                logger.critical("Recovery Level 11: Forcing abort of current task.")
                self.force_abort = True
        except Exception as exc:
            logger.error("SmartAIOrchestrator: Recovery failed: %s", exc)
