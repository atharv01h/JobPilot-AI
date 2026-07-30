"""
Application form filler assistant.
Wrapper for BrowserManager.run_job_application.
"""

from __future__ import annotations

from collections.abc import Callable

from core.logger import get_logger
from core.models import Job

logger = get_logger(__name__)


class FormFiller:
    """
    Wrapper around the single execution pipeline.
    """

    def __init__(
        self,
        confirm_callback: Callable[[Job], bool] | None = None,
        captcha_callback=None,
        login_callback=None,
        otp_callback=None,
    ) -> None:
        self.confirm_callback = confirm_callback
        self.captcha_callback = captcha_callback
        self.login_callback = login_callback
        self.otp_callback = otp_callback

    async def assist_application(self, job: Job) -> bool:
        """
        Full application flow for a single job.
        Returns True if applied successfully.
        """
        from automation.browser_manager import get_browser_manager
        from services.form_service import get_form_service
        from services.resume_service import get_resume_service

        # 1. Pre-flight checks
        resume = get_resume_service()
        error = resume.validate()
        if error:
            logger.error("Resume validation failed: %s", error)
            return False

        form = get_form_service()
        if not form.is_loaded:
            logger.error("Form data not loaded")
            return False

        # 2. Show confirmation dialog BEFORE opening browser
        if self.confirm_callback:
            confirmed = self.confirm_callback(job)
            if not confirmed:
                logger.info(
                    "Application cancelled by user: %s @ %s", job.title, job.company
                )
                return False

        logger.info(
            "Starting application via unified pipeline: %s @ %s", job.title, job.company
        )

        browser = get_browser_manager()
        result = await browser.run_job_application(job)

        if result == "SUCCESS":
            logger.info(
                "Form submitted successfully for %s @ %s", job.title, job.company
            )
            return True

        logger.warning("Form filling incomplete or failed: %s", result)
        return False
