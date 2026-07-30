"""
website_modules.py — Dedicated deterministic automation modules.

V10: Hardened with:
  - Mandatory upload checkpoint (UPLOAD_FAILED stops application immediately)
  - Account/login wall detection via AccountDetector
  - Zero blind-click guard (validates page before every Next/Submit)
  - 5-minute per-application timeout → APPLICATION_TIMEOUT
  - Page fingerprint loop detection → FORM_LOOP
  - Extended ATS platform detection (20+ platforms)
  - Full FailureReason classification on every skip
  - UploadManager V10 with 9-strategy waterfall
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import FrameLocator, Locator, Page

from automation.browser_health import (
    progress_counter,
    record_heartbeat,
    record_progress,
)
from automation.smart_click import smart_click
from automation.smart_input import smart_input
from core.database import get_database
from core.logger import get_logger

logger = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent

# Per-application timeout: 5 minutes
_MAX_APPLICATION_DURATION_S = 300.0
# Fingerprint loop detection: skip if same page seen this many times
_MAX_PAGE_REVISITS = 2


# ─── Application Audit Log ────────────────────────────────────────────────────


class ApplicationAuditLog:
    """
    Records every state transition during a job application for a full audit trail.
    Written to logs/audit_{site}_{timestamp}.json on save().
    """

    def __init__(self, site: str, job_url: str) -> None:
        self.site = site
        self.job_url = job_url
        self.start_time = datetime.now(timezone.utc).isoformat()
        self.entries: list[dict] = []

    def record(self, event: str, detail: str, result: str) -> None:
        self.entries.append(
            {
                "time": datetime.now(timezone.utc).isoformat(),
                "event": event,
                "detail": detail,
                "result": result,
            }
        )

    async def save(self) -> None:
        """Write the audit log to the logs directory."""
        try:
            log_dir = _PROJECT_ROOT / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            safe_site = re.sub(r"[^a-zA-Z0-9_]", "_", self.site)
            filename = log_dir / f"audit_{safe_site}_{ts}.json"
            data = {
                "site": self.site,
                "job_url": self.job_url,
                "start_time": self.start_time,
                "end_time": datetime.now(timezone.utc).isoformat(),
                "entries": self.entries,
            }
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            logger.info("ApplicationAuditLog saved: %s", filename)
        except Exception as exc:
            logger.debug("ApplicationAuditLog.save() failed: %s", exc)


class BaseWebsiteModule:
    NAME = "Base"
    BASE_URL = ""

    def __init__(self, page: Page) -> None:
        self.page = page
        self.job_page = page  # Defaults to same page, overridden for new tabs
        self.processed_jobs: set[str] = set()
        self.max_attempts_per_job = 3
        self.max_attempts_per_selector = 2

    async def _is_nav_element(self, sel: Locator) -> bool:
        """Return True if the element resides within a site header/navigation/menu container."""
        try:
            return await sel.evaluate("""
                el => {
                    let parent = el;
                    while (parent) {
                        const tag = parent.tagName.toLowerCase();
                        const cls = (parent.className || '').toString().toLowerCase();
                        const id = (parent.id || '').toString().toLowerCase();
                        if (tag === 'header' || tag === 'nav' || 
                            cls.includes('header') || cls.includes('nav') || cls.includes('menu') || cls.includes('navbar') ||
                            id.includes('header') || id.includes('nav') || id.includes('menu') || id.includes('navbar')) {
                            return true;
                        }
                        parent = parent.parentElement;
                    }
                    return false;
                }
            """)
        except Exception:
            return False

    async def _compute_page_state_fingerprint(self, page: Page) -> str:
        """
        Computes a comprehensive fingerprint of the current page state.
        Serializes URL, input elements state, visible button labels, and progress steps.
        """
        try:
            state_js = """
            () => {
                const inputs = Array.from(document.querySelectorAll('input, textarea, select, button'));
                const inputStates = inputs.map(el => {
                    const visible = el.offsetWidth > 0 && el.offsetHeight > 0;
                    if (!visible) return '';
                    const tagName = el.tagName.toLowerCase();
                    const type = tagName === 'input' ? (el.getAttribute('type') || 'text') : tagName;
                    const name = el.getAttribute('name') || el.getAttribute('id') || '';
                    const placeholder = el.getAttribute('placeholder') || '';
                    const label = el.getAttribute('aria-label') || el.innerText || '';
                    const value = el.value || '';
                    const checked = el.checked ? '1' : '0';
                    return `${type}:${name}:${placeholder}:${label.substring(0, 20)}:${value.length > 0 ? 1 : 0}:${checked}`;
                }).filter(Boolean).join('|');

                const textElements = Array.from(document.querySelectorAll('h1, h2, h3, span, div, p, li'));
                const progressText = textElements.map(el => {
                    const text = (el.innerText || '').trim();
                    if (/^(step|page|stage)\b.*\\d+/i.test(text) && text.length < 50) {
                        return text;
                    }
                    return '';
                }).filter(Boolean).join(';');

                const buttons = Array.from(document.querySelectorAll('button, [role="button"], input[type="button"], input[type="submit"]'));
                const buttonStates = buttons.map(el => {
                    const visible = el.offsetWidth > 0 && el.offsetHeight > 0;
                    if (!visible) return '';
                    return (el.innerText || el.getAttribute('aria-label') || el.getAttribute('value') || '').trim();
                }).filter(Boolean).join(',');

                return `${inputStates}#${progressText}#${buttonStates}`;
            }
            """
            fingerprint_content = await page.evaluate(state_js)
            return f"{page.url}#{fingerprint_content}"
        except Exception as e:
            logger.debug("Error computing page state fingerprint: %s", e)
            return page.url

    async def attempt_account_creation_or_login(
        self, page: Page, auth_type: str, form_data: dict
    ) -> bool:
        """
        Attempts to handle an authentication wall (Login or Signup/Registration).
        """
        from urllib.parse import urlparse

        domain = urlparse(page.url).netloc.lower() or "generic"
        logger.info(
            "[%s] attempt_account_creation_or_login: domain=%s, type=%s",
            self.NAME,
            domain,
            auth_type,
        )

        personal = form_data.get("personal_details", {})
        email = personal.get("email", "user@example.com")
        first_name = personal.get("first_name", "Candidate")
        last_name = personal.get("last_name", "User")
        phone = personal.get("phone", "+1 555 123 4567")
        password = "SecureJobApply2026!"  # Standard complex password

        from services.auto_login_service import get_auto_login_service

        login_svc = get_auto_login_service()
        has_cred = login_svc.has_credential(domain)

        # Decide action: login if credentials exist, otherwise register
        is_login = (
            has_cred or "login" in auth_type.lower() or "signin" in auth_type.lower()
        )

        # Let's run a loop for up to 3 attempts/stages of login or registration
        for attempt in range(1, 4):
            # Check current page state
            current_url = page.url.lower()
            body_text = ""
            try:
                body_text = await page.inner_text("body", timeout=3000)
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)
            body_l = body_text.lower()

            # Detect page type
            is_login_page = any(
                kw in current_url or kw in body_l
                for kw in [
                    "/login",
                    "/signin",
                    "log in",
                    "sign in",
                    "please sign in",
                    "please log in",
                ]
            )
            is_signup_page = any(
                kw in current_url or kw in body_l
                for kw in [
                    "/register",
                    "/signup",
                    "create account",
                    "create your account",
                    "create an account",
                    "join to apply",
                    "create a candidate account",
                    "create applicant account",
                ]
            )
            is_otp_page = any(
                kw in body_l
                for kw in [
                    "one-time password",
                    "otp",
                    "verification code",
                    "sms code",
                    "verify your phone",
                    "verify your email",
                    "enter the code",
                ]
            )

            logger.info(
                "[%s] Auth Wall step %d: URL=%s, is_login=%s, is_signup=%s, is_otp=%s",
                self.NAME,
                attempt,
                page.url,
                is_login_page,
                is_signup_page,
                is_otp_page,
            )

            if is_otp_page:
                logger.info("[%s] OTP page detected. Querying Gmail...", self.NAME)
                await asyncio.sleep(5.0)  # Wait for email delivery
                from automation.browser_manager import get_browser_manager

                otp = await get_browser_manager().retrieve_gmail_otp_automatic(
                    self.NAME.lower()
                )
                if not otp:
                    # Retry once more with domain name
                    otp = await get_browser_manager().retrieve_gmail_otp_automatic(
                        domain
                    )

                if otp:
                    # Find OTP input and fill it
                    otp_inputs = page.locator(
                        "input[type='text'], input[type='number'], input[id*='otp'], input[name*='otp'], input[placeholder*='code']"
                    )
                    count = await otp_inputs.count()
                    if count > 0:
                        await otp_inputs.first.fill(otp)
                        # Find submit/verify button
                        submit_btn = page.locator(
                            "button:has-text('Verify'), button:has-text('Submit'), button:has-text('Confirm'), button:has-text('Continue')"
                        )
                        if await submit_btn.count() > 0:
                            await submit_btn.first.click()
                        else:
                            await page.keyboard.press("Enter")
                        await asyncio.sleep(4.0)
                        continue

            # Switch page if needed
            if is_login and is_signup_page:
                # We want to login but are on signup page -> find signin link
                signin_link = page.locator(
                    "a:has-text('Sign In'), a:has-text('Log In'), a:has-text('Sign in'), a:has-text('Log in')"
                )
                if await signin_link.count() > 0:
                    await signin_link.first.click()
                    await asyncio.sleep(3.0)
                    continue

            if not is_login and is_login_page:
                # We want to register but are on login page -> find signup/register link
                signup_link = page.locator(
                    "a:has-text('Create Account'), a:has-text('Register'), a:has-text('Sign Up'), a:has-text('Create an Account')"
                )
                if await signup_link.count() > 0:
                    await signup_link.first.click()
                    await asyncio.sleep(3.0)
                    continue

            # Fill Form Fields
            if is_login_page:
                # Fill login form
                email_input = page.locator(
                    "input[type='email'], input[type='text'][name*='email'], input[type='text'][name*='user'], input[id*='email'], input[id*='username']"
                )
                pass_input = page.locator("input[type='password']")

                if await email_input.count() > 0 and await pass_input.count() > 0:
                    cred = login_svc.get_credential(domain)
                    login_email = cred.email or email
                    login_pass = cred.password or password
                    await email_input.first.fill(login_email)
                    await pass_input.first.fill(login_pass)

                    submit_btn = page.locator(
                        "button[type='submit'], button:has-text('Sign In'), button:has-text('Log In'), button:has-text('Login'), button:has-text('Sign in')"
                    )
                    if await submit_btn.count() > 0:
                        await submit_btn.first.click()
                    else:
                        await page.keyboard.press("Enter")
                    await asyncio.sleep(4.0)

                    # If error about invalid account, switch to registration next iteration
                    try:
                        error_text = await page.inner_text("body", timeout=2000)
                        if any(
                            k in error_text.lower()
                            for k in [
                                "not find",
                                "no account",
                                "invalid email",
                                "incorrect username",
                                "not registered",
                            ]
                        ):
                            logger.warning(
                                "[%s] Login failed (user not found). Switching to Register.",
                                self.NAME,
                            )
                            is_login = False
                    except Exception as _exc:
                        logger.debug("Suppressed: %s", _exc)
                    continue

            elif is_signup_page:
                # Fill registration form
                email_input = page.locator(
                    "input[type='email'], input[type='text'][name*='email'], input[id*='email']"
                )
                pass_input = page.locator("input[type='password']").first
                confirm_pass = page.locator(
                    "input[type='password'][name*='confirm'], input[type='password'][id*='confirm'], input[type='password'][name*='repeat']"
                )
                if await confirm_pass.count() == 0:
                    # If only one or two password fields
                    pass_inputs = page.locator("input[type='password']")
                    if await pass_inputs.count() > 1:
                        confirm_pass = pass_inputs.nth(1)

                first_name_input = page.locator(
                    "input[name*='first'], input[id*='first'], input[placeholder*='First']"
                )
                last_name_input = page.locator(
                    "input[name*='last'], input[id*='last'], input[placeholder*='Last']"
                )
                phone_input = page.locator(
                    "input[type='tel'], input[name*='phone'], input[id*='phone']"
                )

                # Fill them
                if await email_input.count() > 0:
                    await email_input.first.fill(email)
                if await pass_input.count() > 0:
                    await pass_input.fill(password)
                if await confirm_pass.count() > 0:
                    await confirm_pass.first.fill(password)
                if await first_name_input.count() > 0:
                    await first_name_input.first.fill(first_name)
                if await last_name_input.count() > 0:
                    await last_name_input.first.fill(last_name)
                if await phone_input.count() > 0:
                    await phone_input.first.fill(phone)

                # Find terms and conditions checkboxes
                checkboxes = page.locator("input[type='checkbox']")
                chk_count = await checkboxes.count()
                for c_idx in range(chk_count):
                    try:
                        chk = checkboxes.nth(c_idx)
                        if await chk.is_visible():
                            await chk.check()
                    except Exception as _exc:
                        logger.debug("Suppressed: %s", _exc)

                # Submit signup
                submit_btn = page.locator(
                    "button[type='submit'], button:has-text('Register'), button:has-text('Create Account'), button:has-text('Sign Up'), button:has-text('Create applicant account')"
                )
                if await submit_btn.count() > 0:
                    await submit_btn.first.click()
                else:
                    await page.keyboard.press("Enter")
                await asyncio.sleep(5.0)

                # Save generated credentials to credentials.json
                login_svc.set_credential(domain, email, password)
                login_svc.save()
                is_login = True  # Treat as logged in next
                continue

            # Fallback if no specific login/signup page structure found, use generic fields filling
            logger.warning(
                "[%s] No explicit login/signup page inputs found, trying generic button click.",
                self.NAME,
            )
            break

        # Check if auth wall is cleared (no login/signup text/URL)
        from automation.account_detector import get_account_detector

        still_blocked = await get_account_detector().detect(page)
        if not still_blocked:
            logger.info("[%s] Auth Wall successfully cleared!", self.NAME)
            return True
        logger.warning("[%s] Auth Wall is still present: %s", self.NAME, still_blocked)
        return False

    async def open_website(self) -> bool:
        logger.info("[%s] Opening website: %s", self.NAME, self.BASE_URL)
        try:
            await self.page.goto(
                self.BASE_URL, timeout=30000, wait_until="domcontentloaded"
            )
            progress_counter.increment("website_opened")
            return True
        except Exception as e:
            logger.error("[%s] Failed to open website: %s", self.NAME, e)
            return False

    async def run_single_apply(
        self,
        job_url: str,
        resume_path: str,
        form_data: dict,
        llm_fn: Callable[[str, str], Awaitable[str]],
    ) -> str:
        """Applies directly to a single job URL using a Task Graph workflow."""
        record_heartbeat("executor")
        logger.info("[%s] Navigating directly to job URL: %s", self.NAME, job_url)
        try:
            await self.page.goto(job_url, timeout=25000, wait_until="domcontentloaded")
            self.job_page = self.page
            progress_counter.increment("website_opened")
        except Exception as e:
            logger.error("[%s] Failed to open job URL: %s", self.NAME, e)
            return "APPLICATION_FAILED"

        state = "CHECK_EASY_APPLY"
        final_result = "APPLICATION_FAILED"

        while state not in [
            "DONE",
            "FAILED",
            "EXTERNAL_APPLICATION_REQUIRED",
            "REDIRECTED_TO_COMPANY",
            "APPLICATION_COMPLETED",
            "APPLICATION_SUBMITTED",
            "APPLICATION_SKIPPED",
            "APPLICATION_FAILED",
        ]:
            record_heartbeat("executor")
            logger.info(
                "[%s] Single Apply Task Graph: Executing state %s", self.NAME, state
            )

            if state == "CHECK_EASY_APPLY":
                is_easy = await self.is_easy_apply()
                if is_easy:
                    progress_counter.increment("easy_apply_detected")
                    state = "START_EASY_APPLY"
                else:
                    logger.info(
                        "[%s] Job at %s is not Easy Apply. Checking for external apply button.",
                        self.NAME,
                        job_url,
                    )
                    state = "CHECK_EXTERNAL_APPLY"

            elif state == "START_EASY_APPLY":
                success = await self.start_easy_apply()
                state = "FILL_AND_SUBMIT" if success else "APPLICATION_FAILED"

            elif state == "FILL_AND_SUBMIT":
                try:
                    applied = await self.fill_form_and_submit(
                        resume_path, form_data, llm_fn
                    )
                    if applied:
                        logger.info(
                            "[%s] Successfully applied (Easy Apply) to Job URL: %s!",
                            self.NAME,
                            job_url,
                        )
                        progress_counter.increment("application_submitted")

                        try:
                            title = await self.job_page.title()
                            db = get_database()
                            from core.models import Job

                            job_obj = Job(title=title, company=self.NAME, url=job_url)
                            job_id_db = await db.insert_job(job_obj)
                            if job_id_db:
                                await db.mark_applied(
                                    job_id_db,
                                    notes="Applied directly via single easy-apply flow",
                                )
                        except Exception as db_err:
                            logger.error(
                                "[%s] Failed to save applied job to database: %s",
                                self.NAME,
                                db_err,
                            )

                        final_result = "APPLICATION_SUBMITTED"
                        state = "DONE"
                    else:
                        final_result = "APPLICATION_FAILED"
                        state = "FAILED"
                except Exception as exc:
                    logger.error("[%s] Error during form fill: %s", self.NAME, exc)
                    final_result = "APPLICATION_FAILED"
                    state = "FAILED"
                finally:
                    if self.job_page != self.page:
                        try:
                            await self.job_page.close()
                        except Exception as _exc:
                            logger.debug("Suppressed: %s", _exc)
                        self.job_page = self.page

            elif state == "CHECK_EXTERNAL_APPLY":
                external_btn = await self.locate_external_apply_button()
                if external_btn:
                    state = "START_EXTERNAL_APPLY"
                else:
                    logger.info(
                        "[%s] No external apply button found for %s", self.NAME, job_url
                    )
                    final_result = "APPLICATION_FAILED"
                    state = "FAILED"

            elif state == "START_EXTERNAL_APPLY":
                external_btn = await self.locate_external_apply_button()
                if external_btn:
                    success = await self.click_external_apply(external_btn)
                    state = "DETECT_ATS" if success else "APPLICATION_FAILED"
                else:
                    final_result = "APPLICATION_FAILED"
                    state = "FAILED"

            elif state == "DETECT_ATS":
                ats = await self.detect_ats_platform()
                logger.info("[%s] Detected ATS platform: %s", self.NAME, ats)

                # Use AccountDetector for comprehensive wall detection
                from automation.account_detector import get_account_detector

                skip_reason = await get_account_detector().detect(self.job_page)
                if skip_reason:
                    # Instead of skipping directly, try to login or register
                    auth_resolved = await self.attempt_account_creation_or_login(
                        self.job_page, skip_reason, form_data
                    )
                    if auth_resolved:
                        state = "FILL_EXTERNAL_FORM"
                    else:
                        logger.warning(
                            "[%s] AccountDetector blocked and auth resolution failed: %s — skipping application.",
                            self.NAME,
                            skip_reason,
                        )
                        final_result = skip_reason
                        state = "DONE"
                else:
                    state = "FILL_EXTERNAL_FORM"

            elif state == "FILL_EXTERNAL_FORM":
                try:
                    success = await self.fill_external_form_generic(
                        resume_path, form_data, llm_fn
                    )
                    state = (
                        "VERIFY_EXTERNAL_SUBMISSION"
                        if success
                        else "APPLICATION_FAILED"
                    )
                except Exception as exc:
                    logger.error(
                        "[%s] Error during external form fill: %s", self.NAME, exc
                    )
                    final_result = "APPLICATION_FAILED"
                    state = "FAILED"

            elif state == "VERIFY_EXTERNAL_SUBMISSION":
                success = await self.verify_external_submission()
                if success:
                    logger.info(
                        "[%s] Successfully applied to external job: %s!",
                        self.NAME,
                        self.job_page.url,
                    )
                    progress_counter.increment("application_submitted")
                    try:
                        title = await self.job_page.title()
                        db = get_database()
                        from core.models import Job

                        job_obj = Job(title=title, company=self.NAME, url=job_url)
                        job_id_db = await db.insert_job(job_obj)
                        if job_id_db:
                            await db.mark_applied(
                                job_id_db,
                                notes="Applied directly via company site flow",
                            )
                    except Exception as db_err:
                        logger.error(
                            "[%s] Failed to save applied job to database: %s",
                            self.NAME,
                            db_err,
                        )
                    final_result = "APPLICATION_SUBMITTED"
                    state = "DONE"
                else:
                    # If we clicked submit but cannot verify, treat as REDIRECTED_TO_COMPANY or EXTERNAL_APPLICATION_REQUIRED
                    logger.warning(
                        "[%s] External submission click finished but could not verify success banner.",
                        self.NAME,
                    )
                    final_result = "EXTERNAL_APPLICATION_REQUIRED"
                    state = "DONE"

        if state in [
            "EXTERNAL_APPLICATION_REQUIRED",
            "REDIRECTED_TO_COMPANY",
            "APPLICATION_COMPLETED",
            "APPLICATION_SUBMITTED",
            "APPLICATION_SKIPPED",
            "APPLICATION_FAILED",
        ]:
            if state == "APPLICATION_FAILED":
                logger.info(
                    "[%s] Single Apply failed. Running AI Navigation Recovery...",
                    self.NAME,
                )
                recovery_success = await self.run_ai_navigation_recovery(
                    resume_path, form_data, llm_fn
                )
                if recovery_success:
                    return "APPLICATION_SUBMITTED"
            return state

        final_result_val = final_result if state == "DONE" else "APPLICATION_FAILED"
        if final_result_val == "APPLICATION_FAILED":
            logger.info(
                "[%s] Single Apply failed. Running AI Navigation Recovery...", self.NAME
            )
            recovery_success = await self.run_ai_navigation_recovery(
                resume_path, form_data, llm_fn
            )
            if recovery_success:
                return "APPLICATION_SUBMITTED"
        return final_result_val

    async def run_search_and_apply(
        self,
        keyword: str,
        location: str,
        resume_path: str,
        form_data: dict,
        llm_fn: Callable[[str, str], Awaitable[str]],
    ) -> str:
        """Runs the entire search and bulk apply workflow using a Task Graph."""
        record_heartbeat("executor")

        state = "OPEN_SITE"
        current_job_card = None
        current_job_id = None
        unprocessed_cards = []

        while state != "DONE" and state != "FAILED":
            record_heartbeat("executor")
            logger.info("[%s] Task Graph: Executing state %s", self.NAME, state)

            if state == "OPEN_SITE":
                success = await self.open_website()
                state = "EXECUTE_SEARCH" if success else "FAILED"

            elif state == "EXECUTE_SEARCH":
                success = await self.search_jobs(keyword, location)
                if success:
                    progress_counter.increment("search_completed")
                    state = "APPLY_FILTERS"
                else:
                    state = "FAILED"

            elif state == "APPLY_FILTERS":
                await self.apply_filters()
                progress_counter.increment("filters_applied")
                state = "LOAD_RESULTS"

            elif state == "LOAD_RESULTS":
                cards = await self.get_job_cards()
                if not cards:
                    logger.info("[%s] Task Graph: No job cards found.", self.NAME)
                    state = "DONE"
                    continue

                unprocessed_cards = []
                for card in cards:
                    job_id = await self.get_job_id(card)
                    if job_id and job_id not in self.processed_jobs:
                        unprocessed_cards.append((card, job_id))

                if not unprocessed_cards:
                    logger.info(
                        "[%s] Task Graph: All visible cards processed.", self.NAME
                    )
                    state = "DONE"
                else:
                    state = "ITERATE_CARDS"

            elif state == "ITERATE_CARDS":
                if not unprocessed_cards:
                    state = "LOAD_RESULTS"
                    continue
                current_job_card, current_job_id = unprocessed_cards.pop(0)
                logger.info(
                    "[%s] Task Graph: Next card to process: %s",
                    self.NAME,
                    current_job_id,
                )
                self.processed_jobs.add(current_job_id)
                state = "OPEN_JOB"

            elif state == "OPEN_JOB":
                try:
                    await current_job_card.scroll_into_view_if_needed(timeout=3000)
                    success = await self.open_job(current_job_card)
                    if success:
                        progress_counter.increment("job_opened")
                        state = "CHECK_EASY_APPLY"
                    else:
                        state = "ITERATE_CARDS"
                except Exception as exc:
                    logger.error(
                        "[%s] Task Graph: Error opening job card: %s", self.NAME, exc
                    )
                    state = "ITERATE_CARDS"

            elif state == "CHECK_EASY_APPLY":
                is_easy = await self.is_easy_apply()
                if is_easy:
                    progress_counter.increment("easy_apply_detected")
                    state = "START_EASY_APPLY"
                else:
                    logger.info(
                        "[%s] Task Graph: Job %s is not Easy Apply. Checking for external apply.",
                        self.NAME,
                        current_job_id,
                    )
                    state = "CHECK_EXTERNAL_APPLY"

            elif state == "CHECK_EXTERNAL_APPLY":
                external_btn = await self.locate_external_apply_button()
                if external_btn:
                    state = "START_EXTERNAL_APPLY"
                else:
                    logger.info(
                        "[%s] Task Graph: Job %s has no external apply button either. Skipping.",
                        self.NAME,
                        current_job_id,
                    )
                    state = "ITERATE_CARDS"

            elif state == "START_EXTERNAL_APPLY":
                external_btn = await self.locate_external_apply_button()
                if external_btn:
                    success = await self.click_external_apply(external_btn)
                    state = "DETECT_ATS" if success else "ITERATE_CARDS"
                else:
                    state = "ITERATE_CARDS"

            elif state == "DETECT_ATS":
                ats = await self.detect_ats_platform()
                logger.info(
                    "[%s] Task Graph: Detected ATS platform: %s for Job %s",
                    self.NAME,
                    ats,
                    current_job_id,
                )

                # Use AccountDetector for comprehensive wall detection
                from automation.account_detector import get_account_detector

                skip_reason = await get_account_detector().detect(self.job_page)
                if skip_reason:
                    # Instead of skipping directly, try to login or register
                    auth_resolved = await self.attempt_account_creation_or_login(
                        self.job_page, skip_reason, form_data
                    )
                    if auth_resolved:
                        state = "FILL_EXTERNAL_FORM"
                    else:
                        logger.warning(
                            "[%s] Task Graph: AccountDetector blocked (%s) for Job %s — skipping.",
                            self.NAME,
                            skip_reason,
                            current_job_id,
                        )
                        try:
                            db = get_database()
                            jobs_list = await db.get_all_jobs()
                            target_job = None
                            for j in jobs_list:
                                if (
                                    j.url == self.job_page.url
                                    or current_job_id in j.url
                                ):
                                    target_job = j
                                    break
                            if target_job:
                                await db.update_job_status(target_job.id, skip_reason)
                        except Exception as db_err:
                            logger.debug(
                                "Failed to update status in bulk search: %s", db_err
                            )
                        if self.job_page != self.page:
                            try:
                                await self.job_page.close()
                            except Exception as _exc:
                                logger.debug("Suppressed: %s", _exc)
                            self.job_page = self.page
                        state = "ITERATE_CARDS"
                else:
                    state = "FILL_EXTERNAL_FORM"

            elif state == "FILL_EXTERNAL_FORM":
                success = False
                try:
                    success = await self.fill_external_form_generic(
                        resume_path, form_data, llm_fn
                    )
                    state = "VERIFY_EXTERNAL_SUBMISSION" if success else "ITERATE_CARDS"
                except Exception as exc:
                    logger.error(
                        "[%s] Task Graph: Error filling external form for Job %s: %s",
                        self.NAME,
                        current_job_id,
                        exc,
                    )
                    state = "ITERATE_CARDS"
                finally:
                    if not success and self.job_page != self.page:
                        try:
                            await self.job_page.close()
                        except Exception as _exc:
                            logger.debug("Suppressed: %s", _exc)
                        self.job_page = self.page

            elif state == "VERIFY_EXTERNAL_SUBMISSION":
                try:
                    success = await self.verify_external_submission()
                    if success:
                        logger.info(
                            "[%s] Task Graph: Successfully applied (External) to Job %s!",
                            self.NAME,
                            current_job_id,
                        )
                        progress_counter.increment("application_submitted")
                        try:
                            title = await self.job_page.title()
                            db = get_database()
                            jobs_list = await db.get_all_jobs()
                            target_job = None
                            for j in jobs_list:
                                if (
                                    j.url == self.job_page.url
                                    or current_job_id in j.url
                                ):
                                    target_job = j
                                    break
                            if target_job:
                                await db.mark_applied(
                                    target_job.id,
                                    self.job_page.url,
                                    notes="Applied deterministically via Task Graph Company Site flow",
                                )
                        except Exception as db_err:
                            logger.error(
                                "[%s] Failed to save applied job to database: %s",
                                self.NAME,
                                db_err,
                            )
                    else:
                        logger.warning(
                            "[%s] Task Graph: Company site submit finished but couldn't verify success banner.",
                            self.NAME,
                        )
                        try:
                            db = get_database()
                            jobs_list = await db.get_all_jobs()
                            target_job = None
                            for j in jobs_list:
                                if (
                                    j.url == self.job_page.url
                                    or current_job_id in j.url
                                ):
                                    target_job = j
                                    break
                            if target_job:
                                await db.update_job_status(
                                    target_job.id, "EXTERNAL_APPLICATION_REQUIRED"
                                )
                        except Exception as db_err:
                            logger.debug(
                                "Failed to set EXTERNAL_APPLICATION_REQUIRED in DB: %s",
                                db_err,
                            )
                except Exception as exc:
                    logger.error(
                        "[%s] Task Graph: Error verifying external submission: %s",
                        self.NAME,
                        exc,
                    )
                finally:
                    if self.job_page != self.page:
                        try:
                            await self.job_page.close()
                        except Exception as _exc:
                            logger.debug("Suppressed: %s", _exc)
                        self.job_page = self.page
                    state = "ITERATE_CARDS"

            elif state == "START_EASY_APPLY":
                success = await self.start_easy_apply()
                if success:
                    state = "FILL_AND_SUBMIT"
                else:
                    logger.info(
                        "[%s] Easy apply failed to start. Running AI Navigation Recovery.",
                        self.NAME,
                    )
                    recovery_success = await self.run_ai_navigation_recovery(
                        resume_path, form_data, llm_fn
                    )
                    if recovery_success:
                        logger.info("[%s] AI Navigation Recovery succeeded!", self.NAME)
                        progress_counter.increment("application_submitted")
                    state = "ITERATE_CARDS"

            elif state == "FILL_AND_SUBMIT":
                try:
                    applied = await self.fill_form_and_submit(
                        resume_path, form_data, llm_fn
                    )
                    if applied:
                        logger.info(
                            "[%s] Task Graph: Successfully applied to Job %s!",
                            self.NAME,
                            current_job_id,
                        )
                        progress_counter.increment("application_submitted")

                        try:
                            title = await self.job_page.title()
                            db = get_database()
                            from core.models import Job

                            job_obj = Job(
                                title=title, company=self.NAME, url=self.job_page.url
                            )
                            job_id_db = await db.insert_job(job_obj)
                            if job_id_db:
                                await db.mark_applied(
                                    job_id_db,
                                    notes="Applied deterministically via Task Graph",
                                )
                        except Exception as db_err:
                            logger.error(
                                "[%s] Failed to save applied job to database: %s",
                                self.NAME,
                                db_err,
                            )

                    else:
                        logger.warning(
                            "[%s] Task Graph: Form submit failed for Job %s. Running AI Navigation Recovery.",
                            self.NAME,
                            current_job_id,
                        )
                        recovery_success = await self.run_ai_navigation_recovery(
                            resume_path, form_data, llm_fn
                        )
                        if recovery_success:
                            logger.info(
                                "[%s] AI Navigation Recovery succeeded!", self.NAME
                            )
                            progress_counter.increment("application_submitted")
                except Exception as exc:
                    logger.error(
                        "[%s] Task Graph: Error applying to job %s: %s. Running AI Navigation Recovery.",
                        self.NAME,
                        current_job_id,
                        exc,
                    )
                    recovery_success = await self.run_ai_navigation_recovery(
                        resume_path, form_data, llm_fn
                    )
                    if recovery_success:
                        logger.info("[%s] AI Navigation Recovery succeeded!", self.NAME)
                        progress_counter.increment("application_submitted")
                finally:
                    if self.job_page != self.page:
                        try:
                            await self.job_page.close()
                        except Exception as _exc:
                            logger.debug("Suppressed: %s", _exc)
                        self.job_page = self.page
                    state = "ITERATE_CARDS"

        return "SUCCESS" if state == "DONE" else "FAILED"

    async def run_ai_navigation_recovery(
        self,
        resume_path: str,
        form_data: dict,
        llm_fn: Callable[[str, str], Awaitable[str]],
    ) -> bool:
        """
        AI Navigation Recovery: runs when a deterministic step fails.
        Captures page state, queries the AINavigationEngine for actions,
        and executes them iteratively. Returns True if application is successfully submitted.
        """
        logger.info("[%s] Initiating AI Navigation Recovery...", self.NAME)

        # Initialize AI Navigation Engine
        from automation.ai_navigation import AINavigationEngine

        nav_engine = AINavigationEngine(self.job_page)

        from services.resume_intelligence import get_resume_intelligence

        resume_intel = get_resume_intelligence()
        resume_context = ""
        try:
            if not resume_intel.is_ready():
                await resume_intel.initialize()
            if resume_intel.is_ready():
                resume_context = resume_intel.get_profile().to_context_string()
        except Exception as e:
            logger.debug("Failed to initialize resume intelligence for recovery: %s", e)

        profile_summary = json.dumps(form_data, indent=2)
        previous_actions = []

        max_recovery_steps = 10
        step = 0

        while step < max_recovery_steps:
            record_heartbeat("executor")
            step += 1
            logger.info(
                "[%s] AI Recovery Step %d/%d", self.NAME, step, max_recovery_steps
            )

            # Pause and wait for transitions / animations to settle
            await self.job_page.wait_for_timeout(2000)

            # Capture current state
            state_data = await nav_engine.capture_state()

            # Check if page text or URL suggests success/submission confirmation
            url_lower = state_data["url"].lower()
            page_text_lower = state_data["page_text"].lower()

            # Common submission confirmation indicators
            confirmation_keywords = [
                "submitted",
                "thank you",
                "application received",
                "success",
                "confirmation",
                "received your application",
            ]
            is_submitted = (
                any(kw in page_text_lower for kw in confirmation_keywords)
                or "thank-you" in url_lower
                or "confirmation" in url_lower
            )

            if is_submitted:
                logger.info(
                    "[%s] AI Recovery: Submission confirmation detected in page content/URL!",
                    self.NAME,
                )
                return True

            # Call AINavigationEngine to plan next action
            dom_summary = (
                f"Page Title: {state_data['title']}\nURL: {state_data['url']}\n"
            )
            dom_summary += (
                f"Visible clickable count: {len(state_data['visible_elements'])}\n"
            )

            # Call AI
            decision = await nav_engine.get_next_action(
                dom_summary=dom_summary,
                visible_elements=state_data["visible_elements"],
                accessibility_tree=state_data["accessibility_tree"],
                ocr_text=state_data["page_text"],
                screenshot_b64=state_data["screenshot_b64"],
                url=state_data["url"],
                title=state_data["title"],
                previous_actions=previous_actions,
                resume_context=resume_context,
                profile_summary=profile_summary,
                current_stage="RECOVERY",
            )

            logger.info(
                "[%s] AI Recovery Decision: %s",
                self.NAME,
                json.dumps(decision, indent=2),
            )

            action = decision.get("action", {})
            action_type = action.get("type")

            if not action_type or action_type == "wait":
                seconds = action.get("seconds", 2)
                logger.info(
                    "[%s] AI Action: Waiting for %d seconds...", self.NAME, seconds
                )
                await self.job_page.wait_for_timeout(seconds * 1000)
                previous_actions.append(f"wait {seconds}s")
                continue

            if action_type == "scroll":
                direction = action.get("direction", "down")
                logger.info("[%s] AI Action: Scrolling %s", self.NAME, direction)
                if direction == "down":
                    await self.job_page.evaluate(
                        "window.scrollBy(0, window.innerHeight)"
                    )
                else:
                    await self.job_page.evaluate(
                        "window.scrollBy(0, -window.innerHeight)"
                    )
                previous_actions.append(f"scroll {direction}")
                continue

            if action_type == "submit":
                logger.info("[%s] AI Action: Pressing Submit button", self.NAME)
                submit_selectors = [
                    "button[type='submit']",
                    "input[type='submit']",
                    "button:has-text('Submit')",
                    "button:has-text('Submit Application')",
                    "button:has-text('Finish')",
                    "button:has-text('Apply')",
                ]
                clicked = False
                for sel in submit_selectors:
                    try:
                        loc = self.job_page.locator(sel).first
                        if await loc.count() > 0 and await loc.is_visible():
                            await loc.click(timeout=5000)
                            clicked = True
                            logger.info(
                                "[%s] Clicked submit via selector '%s'", self.NAME, sel
                            )
                            break
                    except Exception:
                        continue
                if not clicked:
                    logger.warning(
                        "[%s] Could not find specific submit button, scrolling down",
                        self.NAME,
                    )
                    await self.job_page.evaluate(
                        "window.scrollTo(0, document.body.scrollHeight)"
                    )
                previous_actions.append("submit")
                continue

            element_index = action.get("element_index")
            if element_index is None:
                logger.warning("[%s] AI Action has no element_index", self.NAME)
                previous_actions.append(f"failed_action_{action_type}_no_index")
                continue

            elements = state_data["visible_elements"]
            if element_index < 0 or element_index >= len(elements):
                logger.warning(
                    "[%s] AI Action element_index %d out of bounds",
                    self.NAME,
                    element_index,
                )
                previous_actions.append(f"failed_action_{action_type}_out_of_bounds")
                continue

            el_data = elements[element_index]
            tag = el_data.get("tag", "")
            el_id = el_data.get("id", "")
            el_name = el_data.get("name", "")
            el_text = el_data.get("text", "")

            locator = None
            if el_id:
                locator = self.job_page.locator(f"#{el_id}").first
            elif el_name:
                locator = self.job_page.locator(f"{tag}[name='{el_name}']").first
            elif el_text:
                escaped_text = el_text.replace("'", "\\'")
                locator = self.job_page.locator(
                    f"{tag}:has-text('{escaped_text}')"
                ).first

            if not locator or await locator.count() == 0:
                try:
                    locator = self.job_page.locator(tag).nth(el_data["index"])
                except Exception:
                    logger.warning(
                        "[%s] Could not locate element with index %d",
                        self.NAME,
                        element_index,
                    )
                    previous_actions.append(f"failed_locate_element_{element_index}")
                    continue

            try:
                if action_type == "click":
                    logger.info(
                        "[%s] AI Action: Clicking element '%s' (%s)",
                        self.NAME,
                        el_text or el_id or el_name,
                        tag,
                    )
                    await locator.scroll_into_view_if_needed(timeout=5000)
                    await locator.click(timeout=5000)
                    previous_actions.append(f"clicked {el_text or el_id or el_name}")

                elif action_type == "fill":
                    val = action.get("value", "")
                    logger.info(
                        "[%s] AI Action: Filling element '%s' with '%s'",
                        self.NAME,
                        el_text or el_id or el_name,
                        val,
                    )
                    await locator.scroll_into_view_if_needed(timeout=5000)
                    await locator.fill(val, timeout=5000)
                    previous_actions.append(f"filled {el_id or el_name} with value")

                elif action_type == "upload":
                    logger.info(
                        "[%s] AI Action: Uploading resume to element '%s'",
                        self.NAME,
                        el_text or el_id or el_name,
                    )
                    from automation.upload_manager import get_upload_manager

                    um = get_upload_manager()
                    up_res = await um.upload(
                        self.job_page,
                        site=self.NAME,
                        container=locator,
                        resume_path=resume_path,
                    )
                    if up_res.success:
                        logger.info(
                            "[%s] Upload successful via AI navigation upload action!",
                            self.NAME,
                        )
                        previous_actions.append("uploaded_resume_success")
                    else:
                        logger.warning(
                            "[%s] Upload failed via AI navigation: %s",
                            self.NAME,
                            up_res.failure_reason,
                        )
                        previous_actions.append("uploaded_resume_failed")

                elif action_type == "select":
                    opt = action.get("option_text", "")
                    logger.info(
                        "[%s] AI Action: Selecting option '%s' on element '%s'",
                        self.NAME,
                        opt,
                        el_text or el_id or el_name,
                    )
                    await locator.scroll_into_view_if_needed(timeout=5000)
                    try:
                        await locator.select_option(label=opt, timeout=5000)
                    except Exception:
                        await locator.select_option(value=opt, timeout=5000)
                    previous_actions.append(f"selected {opt}")

                elif action_type == "check":
                    logger.info(
                        "[%s] AI Action: Checking checkbox element '%s'",
                        self.NAME,
                        el_text or el_id or el_name,
                    )
                    await locator.scroll_into_view_if_needed(timeout=5000)
                    await locator.check(timeout=5000)
                    previous_actions.append(f"checked {el_id or el_name}")

            except Exception as e:
                logger.error(
                    "[%s] AI Action execution failed for type '%s': %s",
                    self.NAME,
                    action_type,
                    e,
                )
                previous_actions.append(f"action_failed_{action_type}")

        logger.warning(
            "[%s] AI Recovery finished: reached maximum steps (%d) without verified submission.",
            self.NAME,
            max_recovery_steps,
        )
        return False

    async def _get_question_for_group(
        self, container: Page | FrameLocator, page: Page, element: Locator
    ) -> str:
        """Finds the main question/header text for a form field group."""
        try:
            js_script = """
            el => {
                const clean = s => s ? s.replace(/\\s+/g, ' ').trim() : '';
                const fieldset = el.closest('fieldset');
                if (fieldset) {
                    const legend = fieldset.querySelector('legend');
                    if (legend && clean(legend.innerText)) return clean(legend.innerText);
                }
                const container = el.closest('.form-group, .question-container, div[class*="question"], div[class*="group"], div[class*="field"]');
                if (container) {
                    const label = container.querySelector('label, .label, [class*="label"], [class*="question-text"]');
                    if (label && clean(label.innerText)) return clean(label.innerText);
                    const firstChild = container.firstElementChild;
                    if (firstChild && clean(firstChild.innerText)) return clean(firstChild.innerText);
                }
                return '';
            }
            """
            return await element.evaluate(js_script)
        except Exception:
            return ""

    async def _get_label_for_element_on_container(
        self, container: Page | FrameLocator, page: Page, element: Locator
    ) -> str:
        """Resolves label text for a given form element using multiple heuristics."""
        try:
            js_script = """
            el => {
                const clean = s => s ? s.replace(/\\s+/g, ' ').trim() : '';
                if (el.placeholder && clean(el.placeholder)) return clean(el.placeholder);
                if (el.getAttribute('aria-label') && clean(el.getAttribute('aria-label'))) return clean(el.getAttribute('aria-label'));
                
                if (el.id) {
                    const label = document.querySelector(`label[for="${el.id}"]`);
                    if (label && clean(label.innerText)) return clean(label.innerText);
                }
                
                const parentLabel = el.closest('label');
                if (parentLabel && clean(parentLabel.innerText)) return clean(parentLabel.innerText);
                
                const parent = el.parentElement;
                if (parent) {
                    let sibling = el.previousElementSibling;
                    while (sibling) {
                        if (['LABEL', 'SPAN', 'P', 'DIV', 'H3', 'H4'].includes(sibling.tagName) && clean(sibling.innerText)) {
                            const txt = clean(sibling.innerText);
                            if (txt.length > 2 && txt.length < 200) return txt;
                        }
                        sibling = sibling.previousElementSibling;
                    }
                    const txt = clean(parent.innerText);
                    if (txt && txt.length > 2 && txt.length < 200) {
                        return txt;
                    }
                }
                return '';
            }
            """
            label_text = await element.evaluate(js_script)
            if label_text:
                return label_text.strip()
        except Exception as e:
            logger.debug("[%s] JS label resolution failed: %s", self.NAME, e)

        try:
            placeholder = await element.get_attribute("placeholder")
            if placeholder and placeholder.strip():
                return placeholder.strip()

            aria_label = await element.get_attribute("aria-label")
            if aria_label and aria_label.strip():
                return aria_label.strip()

            el_id = await element.get_attribute("id")
            if el_id:
                label_el = container.locator(f"label[for='{el_id}']").first
                if await label_el.count() > 0:
                    return (await label_el.inner_text()).strip()

            parent_label = element.locator("xpath=ancestor::label").first
            if await parent_label.count() > 0:
                return (await parent_label.inner_text()).strip()
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)
        return ""

    async def get_element_context(self, page: Page, element: Locator) -> dict:
        """Extracts label, placeholder, validation text, and nearby context from the DOM for a form element."""
        try:
            js_script = """
            el => {
                const clean = s => s ? s.replace(/\\s+/g, ' ').trim() : '';
                const parent = el.closest('.form-group, .question-container, div[class*="question"], div[class*="group"], div[class*="field"], tr, td');
                
                let label = '';
                let placeholder = el.placeholder || el.getAttribute('placeholder') || '';
                let validationText = '';
                let nearbyText = '';
                
                // 1. Get Label
                if (el.id) {
                    const lblEl = document.querySelector(`label[for="${el.id}"]`);
                    if (lblEl) label = lblEl.innerText;
                }
                if (!label) {
                    const parentLabel = el.closest('label');
                    if (parentLabel) label = parentLabel.innerText;
                }
                if (!label && parent) {
                    const lblEl = parent.querySelector('label, .label, [class*="label"], [class*="question-text"]');
                    if (lblEl) label = lblEl.innerText;
                }
                
                // 2. Get Validation/Error Text
                if (parent) {
                    const errEl = parent.querySelector('.error, .error-message, .validation-message, [class*="error"], [class*="validation"]');
                    if (errEl) validationText = errEl.innerText;
                }
                
                // 3. Get Nearby Text Context (e.g. instruction texts, descriptions)
                if (parent) {
                    nearbyText = parent.innerText;
                } else {
                    let sib = el.previousElementSibling;
                    while (sib) {
                        nearbyText += ' ' + sib.innerText;
                        sib = sib.previousElementSibling;
                    }
                }
                
                return {
                    label: clean(label),
                    placeholder: clean(placeholder),
                    validationText: clean(validationText),
                    nearbyText: clean(nearbyText).substring(0, 1000)
                };
            }
            """
            return await element.evaluate(js_script)
        except Exception as e:
            logger.debug("Failed to get element context: %s", e)
            return {
                "label": "",
                "placeholder": "",
                "validationText": "",
                "nearbyText": "",
            }

    async def fill_form_fields_on_container(
        self,
        container: Page | FrameLocator,
        page: Page,
        resume_path: str,
        form_data: dict,
        llm_fn: Callable[[str, str], Awaitable[str]],
    ) -> None:
        """Deterministically identifies and fills form elements within the scoped container."""
        from services.form_intelligence import get_form_intelligence_engine

        engine = get_form_intelligence_engine()

        # 1. File Upload (Resume)
        file_inputs = container.locator("input[type='file']")
        for i in range(await file_inputs.count()):
            f_input = file_inputs.nth(i)
            try:
                if await self._is_nav_element(f_input):
                    continue
                if await f_input.is_visible():
                    await f_input.set_files(resume_path)
                    logger.info("[%s] Uploaded resume to file input", self.NAME)
                    progress_counter.increment("resume_uploaded")
            except Exception as e:
                logger.debug("[%s] File input upload failed: %s", self.NAME, e)

        # 2. Text / Textarea / Number / URL / Date Inputs
        text_inputs = container.locator(
            "input[type='text'], input[type='email'], input[type='tel'], "
            "input[type='number'], input[type='url'], input[type='date'], "
            "input:not([type]), textarea"
        )
        for i in range(await text_inputs.count()):
            ipt = text_inputs.nth(i)
            try:
                if await self._is_nav_element(ipt):
                    continue
                if not await ipt.is_visible() or not await ipt.is_enabled():
                    continue

                curr_val = await ipt.input_value()
                if curr_val and len(curr_val.strip()) > 1:
                    continue  # skip already filled

                label_text = await self._get_label_for_element_on_container(
                    container, page, ipt
                )
                if not label_text:
                    continue

                ctx = await self.get_element_context(page, ipt)
                val = await engine.get_answer(
                    label_text,
                    "text input",
                    llm_fn,
                    page=page,
                    locator=ipt,
                    site=self.NAME,
                    context_data=ctx,
                )
                if val:
                    label_lower = label_text.lower()
                    if "first name" in label_lower and len(val.split()) > 1:
                        val = val.split()[0]
                    elif "last name" in label_lower and len(val.split()) > 1:
                        val = val.split()[-1]
                    await smart_input(container, ipt, val)
            except Exception as e:
                logger.debug("[%s] Text element filling failed: %s", self.NAME, e)

        # 3. Select / Dropdowns
        selects = container.locator("select")
        for i in range(await selects.count()):
            sel = selects.nth(i)
            try:
                if await self._is_nav_element(sel):
                    continue
                if not await sel.is_visible() or not await sel.is_enabled():
                    continue

                label_text = await self._get_label_for_element_on_container(
                    container, page, sel
                )
                if label_text:
                    ctx = await self.get_element_context(page, sel)
                    ans = await engine.get_answer(
                        label_text,
                        "dropdown option",
                        llm_fn,
                        page=page,
                        locator=sel,
                        site=self.NAME,
                        context_data=ctx,
                    )
                    if ans:
                        options = await sel.locator("option").all()
                        best_val = None
                        for opt in options:
                            opt_txt = await opt.inner_text()
                            if (
                                ans.lower() in opt_txt.lower()
                                or opt_txt.lower() in ans.lower()
                            ):
                                best_val = await opt.get_attribute("value") or opt_txt
                                break
                        if best_val:
                            await sel.select_option(best_val)
            except Exception as e:
                logger.debug("[%s] Select option failed: %s", self.NAME, e)

        # 4. Custom comboboxes and listboxes
        try:
            custom_selects = container.locator(
                "div[role='button'][aria-haspopup='listbox'], div[role='combobox'], "
                "[class*='select-container'], [class*='dropdown-toggle']"
            )
            for i in range(await custom_selects.count()):
                sel = custom_selects.nth(i)
                try:
                    if await self._is_nav_element(sel):
                        continue
                    if not await sel.is_visible() or not await sel.is_enabled():
                        continue
                    label_text = await self._get_label_for_element_on_container(
                        container, page, sel
                    )
                    if not label_text:
                        continue
                    ctx = await self.get_element_context(page, sel)
                    ans = await engine.get_answer(
                        label_text,
                        "dropdown option",
                        llm_fn,
                        page=page,
                        locator=sel,
                        site=self.NAME,
                        context_data=ctx,
                    )
                    if ans:
                        await smart_click(container, sel)
                        await page.wait_for_timeout(1000)
                        options = page.locator(
                            "[role='option'], li, .option, [class*='dropdown-item']"
                        )
                        best_option = None
                        for j in range(await options.count()):
                            opt = options.nth(j)
                            try:
                                opt_txt = await opt.inner_text()
                                if (
                                    ans.lower() in opt_txt.lower()
                                    or opt_txt.lower() in ans.lower()
                                ):
                                    best_option = opt
                                    break
                            except Exception:
                                continue
                        if best_option:
                            await smart_click(page, best_option)
                        else:
                            await smart_click(container, sel)
                except Exception as e:
                    logger.debug(
                        "[%s] Custom select dropdown handling failed for element %d: %s",
                        self.NAME,
                        i,
                        e,
                    )
        except Exception as e:
            logger.debug("[%s] Custom selects scanning failed: %s", self.NAME, e)

        # 5. Radio Buttons
        try:
            radios = container.locator("input[type='radio']")
            radio_groups = {}
            for i in range(await radios.count()):
                rad = radios.nth(i)
                if await self._is_nav_element(rad):
                    continue
                if not await rad.is_visible() or not await rad.is_enabled():
                    continue
                name = await rad.get_attribute("name") or "unnamed_group"
                if name not in radio_groups:
                    radio_groups[name] = []
                radio_groups[name].append(rad)

            for name, group in radio_groups.items():
                already_checked = False
                for rad in group:
                    if await rad.is_checked():
                        already_checked = True
                        break
                if already_checked:
                    continue

                question = await self._get_question_for_group(container, page, group[0])
                if not question:
                    question = await self._get_label_for_element_on_container(
                        container, page, group[0]
                    )

                options_data = []
                for rad in group:
                    lbl = await self._get_label_for_element_on_container(
                        container, page, rad
                    )
                    options_data.append((rad, lbl))

                if not question or not options_data:
                    continue

                options_str = ", ".join([f"'{lbl}'" for _, lbl in options_data])
                ctx = await self.get_element_context(page, group[0])
                ans = await engine.get_answer(
                    f"{question} (Options: {options_str})",
                    "radio group",
                    llm_fn,
                    page=page,
                    locator=group[0],
                    site=self.NAME,
                    context_data=ctx,
                )

                chosen_rad = None
                if ans:
                    for rad, lbl in options_data:
                        if ans.lower() in lbl.lower() or lbl.lower() in ans.lower():
                            chosen_rad = rad
                            break

                if not chosen_rad:
                    chosen_rad = group[0]

                await smart_click(container, chosen_rad)
        except Exception as e:
            logger.debug("[%s] Radio filling failed: %s", self.NAME, e)

        # 6. Checkboxes
        try:
            checkboxes = container.locator("input[type='checkbox']")
            for i in range(await checkboxes.count()):
                cb = checkboxes.nth(i)
                if await self._is_nav_element(cb):
                    continue
                if (
                    not await cb.is_visible()
                    or not await cb.is_enabled()
                    or await cb.is_checked()
                ):
                    continue

                label_text = await self._get_label_for_element_on_container(
                    container, page, cb
                )
                label_lower = label_text.lower()

                should_check = False
                if any(
                    kw in label_lower
                    for kw in [
                        "agree",
                        "terms",
                        "policy",
                        "privacy",
                        "understand",
                        "acknowledge",
                        "correct",
                        "true",
                    ]
                ):
                    should_check = True
                else:
                    ctx = await self.get_element_context(page, cb)
                    ans = await engine.get_answer(
                        f"Should the applicant check this box: {label_text}",
                        "checkbox yes/no",
                        llm_fn,
                        page=page,
                        locator=cb,
                        site=self.NAME,
                        context_data=ctx,
                    )
                    if ans and "yes" in ans.lower():
                        should_check = True

                if should_check:
                    await cb.check()
        except Exception as e:
            logger.debug("[%s] Checkbox filling failed: %s", self.NAME, e)

    # ══════════════════════════════════════════════════════════════════
    # V9 ─ Modal Manager
    # ══════════════════════════════════════════════════════════════════

    async def get_active_modal_type(self, page: Page) -> str:
        """
        Return the current modal type using DOM signals first, vision fallback.
        Returns: easy_apply | resume_upload | multi_step_form | success | error |
                 captcha | login | none | unknown
        """
        # 1. Fast DOM check for known success / error patterns
        try:
            body = await page.inner_text("body", timeout=3000)
            body_l = body.lower()
            if any(
                kw in body_l
                for kw in [
                    "application submitted",
                    "successfully applied",
                    "your application was sent",
                    "apply success",
                    "thank you for applying",
                    "we've received",
                ]
            ):
                return "success"
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)

        # 2. Vision fallback
        try:
            from automation.vision_engine import get_vision_engine

            engine = get_vision_engine()
            if engine._enabled:
                return await engine.detect_modal_state(page)
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)
        return "unknown"

    async def wait_for_modal_to_close(
        self, page: Page, modal_selector: str, timeout_s: float = 15.0
    ) -> bool:
        """Wait until the modal identified by selector disappears. Returns True if gone."""
        deadline = asyncio.get_event_loop().time() + timeout_s
        while asyncio.get_event_loop().time() < deadline:
            try:
                if await page.locator(modal_selector).count() == 0:
                    return True
            except Exception:
                return True
            await asyncio.sleep(0.5)
        return False

    # ══════════════════════════════════════════════════════════════════
    # V9 ─ Smart Button Engine
    # ══════════════════════════════════════════════════════════════════

    async def click_smart_button(
        self,
        container,
        page: Page,
        button_type: str = "next",
    ) -> bool:
        """
        Find and click the appropriate button (next/submit) using a flexible
        text-based scan.  Never hardcodes to a single phrase.

        button_type: "next" | "submit"
        Returns True if a button was clicked.
        """
        if button_type == "submit":
            candidates = [
                "Submit application",
                "Submit",
                "Apply",
                "Finish",
                "Complete application",
                "Confirm and apply",
                "Send application",
                "Done",
                "Apply now",
                "Submit Application",
            ]
        else:  # next / continue
            candidates = [
                "Next",
                "Continue",
                "Review",
                "Save",
                "Next step",
                "Continue to review",
                "Review application",
                "Save and Continue",
                "Save & Continue",
            ]

        # Exact text match first (fastest)
        for text in candidates:
            try:
                btn = container.get_by_role(
                    "button", name=re.compile(re.escape(text), re.IGNORECASE)
                ).first
                if (
                    await btn.count() > 0
                    and await btn.is_visible()
                    and await btn.is_enabled()
                ) and await smart_click(container, btn):
                    record_progress(f"smart_button_clicked_{button_type}_{text}")
                    logger.info(
                        "[%s] SmartButton: clicked '%s' (%s)",
                        self.NAME,
                        text,
                        button_type,
                    )
                    return True
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

        # Fallback: scan all buttons and pick best text match
        try:
            all_btns = container.locator("button:visible")
            count = await all_btns.count()
            for i in range(count):
                btn = all_btns.nth(i)
                try:
                    txt = (await btn.inner_text()).strip().lower()
                    if not await btn.is_enabled():
                        continue
                    match = any(
                        c.lower() in txt or txt in c.lower() for c in candidates
                    )
                    if match and await smart_click(container, btn):
                        record_progress(f"smart_button_fallback_{button_type}")
                        logger.info(
                            "[%s] SmartButton fallback: clicked '%s'",
                            self.NAME,
                            txt,
                        )
                        return True
                except Exception:
                    continue
        except Exception as exc:
            logger.debug("[%s] SmartButton scan error: %s", self.NAME, exc)
        return False

    # ══════════════════════════════════════════════════════════════════
    # V9 ─ Verified Resume Upload (4-Stage)
    # ══════════════════════════════════════════════════════════════════

    async def upload_resume_verified(
        self, container, page: Page, resume_path: str
    ) -> bool:
        """
        Upload resume by delegating to UploadManager.
        Returns True only if upload succeeded AND was verified.
        """
        from automation.upload_manager import get_upload_manager

        uploader = get_upload_manager()
        res = await uploader.upload(
            page=page,
            site=self.NAME.lower(),
            container=container,
            resume_path=resume_path,
        )
        if res.success:
            logger.info("[%s] Resume upload succeeded via UploadManager.", self.NAME)
            return True
        else:
            logger.warning(
                "[%s] Resume upload FAILED: %s", self.NAME, res.failure_reason
            )
            return False

    async def _is_upload_required(self, page: Page, container=None) -> bool:
        """
        Return True if the current page contains an upload widget.
        Used to determine if upload is a mandatory checkpoint on this step.
        """
        from automation.upload_manager import get_upload_manager

        uploader = get_upload_manager()
        return await uploader.is_upload_required_on_page(page, container)

    async def _is_upload_already_done(self, page: Page, filename: str) -> bool:
        """
        Return True if the page already shows signs of a completed upload.
        Prevents re-uploading on every form step.
        """
        from automation.upload_manager import get_upload_manager

        uploader = get_upload_manager()
        return await uploader.is_upload_already_verified(page, filename)

    async def _validate_page_before_click(
        self, page: Page, container, resume_path: str
    ) -> tuple[bool, str]:
        """
        Zero-blind-click guard: validate the current page state before
        pressing any Next/Continue/Save/Review/Submit button.

        Returns (ok: bool, reason: str).
        ok=True means it is safe to click.
        ok=False means something is wrong — do NOT click.
        """
        from automation.vision_engine import get_vision_engine

        # Check 1: No visible form validation errors
        try:
            vision = get_vision_engine()
            if vision._enabled:
                errors = await vision.detect_form_errors(page)
                if errors:
                    logger.warning(
                        "[%s] Pre-click guard: %d validation errors visible: %s",
                        self.NAME,
                        len(errors),
                        errors,
                    )
                    return False, f"validation_errors: {errors}"
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)

        # Check 2: If upload widget present, verify it was completed
        if resume_path:
            upload_required = await self._is_upload_required(page, container)
            if upload_required:
                filename = Path(resume_path).name
                upload_done = await self._is_upload_already_done(page, filename)
                if not upload_done:
                    logger.error(
                        "[%s] Pre-click guard: UPLOAD REQUIRED but NOT completed — BLOCKING button click.",
                        self.NAME,
                    )
                    return False, "upload_required_not_completed"

        return True, "ok"

    async def detect_form_errors_dom(self, page: Page) -> list[str]:
        """Fast DOM-based validation error check returning error texts."""
        errors = []
        try:
            # 1. Inputs marked invalid
            invalid_elements = page.locator(
                "input[aria-invalid='true'], select[aria-invalid='true'], textarea[aria-invalid='true']"
            )
            count = await invalid_elements.count()
            for i in range(count):
                el = invalid_elements.nth(i)
                name = (
                    await el.get_attribute("name")
                    or await el.get_attribute("id")
                    or "field"
                )
                errors.append(f"Field '{name}' is marked invalid.")

            # 2. Visual error classes / messages
            error_msg_selectors = [
                ".error-message",
                ".errorMessage",
                ".form-error",
                ".field-error",
                "[class*='error-message']",
                "[class*='invalid-feedback']",
                "[class*='field-error']",
                "[role='alert']",
            ]
            for sel in error_msg_selectors:
                elements = page.locator(sel)
                cnt = await elements.count()
                for i in range(cnt):
                    el = elements.nth(i)
                    if await el.is_visible():
                        text = (await el.inner_text()).strip()
                        if text:
                            errors.append(text)
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)
        return errors

    # ══════════════════════════════════════════════════════════════════
    # V9 ─ Multi-Step Form Engine (replaces fill_form_and_submit_generic)
    # ══════════════════════════════════════════════════════════════════

    async def fill_form_and_submit_generic(
        self,
        resume_path: str,
        form_data: dict,
        llm_fn: Callable[[str, str], Awaitable[str]],
        submit_selectors: list[str],
        next_selectors: list[str],
        form_container_selector: str | None = None,
    ) -> bool:
        """
        V10 Hardened Multi-Step Form Engine.

        Critical invariants:
          - Upload is a MANDATORY CHECKPOINT: if upload required but fails,
            return False immediately — NEVER click Next/Continue/Save/Submit after failed upload.
          - Zero blind clicking: validate page state before every button click.
          - 5-minute application timeout → return False with TIMEOUT reason.
          - Page fingerprint loop detection → abort on FORM_LOOP.
          - Upload deduplication: never upload again once verified this session.
        """
        max_steps = 15
        page = self.job_page
        audit = ApplicationAuditLog(site=self.NAME, job_url=page.url)
        last_state_fingerprint = ""
        identical_state_count = 0
        stuck_count = 0
        # Reset upload session state for this application
        from automation.upload_manager import get_upload_manager

        upload_mgr = get_upload_manager()
        upload_mgr.reset_session()
        # Application-level timeout
        app_start = time.monotonic()
        filename = Path(resume_path).name if resume_path else ""

        from automation.vision_engine import get_vision_engine

        vision = get_vision_engine()

        for step in range(1, max_steps + 1):
            record_heartbeat("executor")
            audit.record("step_start", f"Step {step}", "entering")
            logger.info("[%s] Form engine: Step %d/%d", self.NAME, step, max_steps)

            # ── TIMEOUT CHECK ──────────────────────────────────────────────
            elapsed = time.monotonic() - app_start
            if elapsed > _MAX_APPLICATION_DURATION_S:
                logger.error(
                    "[%s] Form engine: APPLICATION_TIMEOUT — %.0fs elapsed (limit=%ds). Aborting.",
                    self.NAME,
                    elapsed,
                    _MAX_APPLICATION_DURATION_S,
                )
                audit.record(
                    "timeout", f"elapsed={elapsed:.0f}s", "APPLICATION_TIMEOUT"
                )
                await audit.save()
                return False

            # ── Check for success confirmation ─────────────────────────────
            modal_type = await self.get_active_modal_type(page)
            if modal_type == "success":
                audit.record("confirmation", "success_detected", "done")
                logger.info(
                    "[%s] Form engine: Success confirmed at step %d.", self.NAME, step
                )
                await audit.save()
                return True

            # ── Vision confirmation check ──────────────────────────────────
            try:
                if vision._enabled and await vision.detect_confirmation(page):
                    audit.record("vision_confirmation", "confirmed", "done")
                    logger.info(
                        "[%s] Form engine: Vision confirms submission success.",
                        self.NAME,
                    )
                    await audit.save()
                    return True
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

            # ── LOOP DETECTION — page fingerprint ──────────────────────────
            current_state_fingerprint = await self._compute_page_state_fingerprint(page)
            if current_state_fingerprint == last_state_fingerprint:
                identical_state_count += 1
                logger.warning(
                    "[%s] Form engine: Identical state detected (%d/10).",
                    self.NAME,
                    identical_state_count,
                )
                if identical_state_count >= 10:
                    logger.error(
                        "[%s] Form engine: FORM_LOOP detected — 10 identical states with zero DOM change. Aborting.",
                        self.NAME,
                    )
                    audit.record(
                        "form_loop",
                        "10 identical states with zero DOM change",
                        "FORM_LOOP",
                    )
                    await audit.save()
                    return False
            else:
                identical_state_count = 0
                last_state_fingerprint = current_state_fingerprint

            # ── Resolve container (iframe or page) ─────────────────────────
            iframe_selector = "iframe[src*='indeedapply'], iframe[title*='Indeed'], iframe[src*='apply']"
            if await page.locator(iframe_selector).count() > 0:
                container = page.frame_locator(iframe_selector)
                logger.debug("[%s] Form engine: using iframe container.", self.NAME)
            elif (
                form_container_selector
                and await page.locator(form_container_selector).count() > 0
            ):
                container = page.locator(form_container_selector).first
            else:
                container = page

            # ── MANDATORY UPLOAD CHECKPOINT ────────────────────────────────
            # Check if this page requires an upload before we can proceed
            if resume_path:
                upload_required = await self._is_upload_required(page, container)
                if upload_required:
                    already_done = await self._is_upload_already_done(page, filename)
                    if not already_done:
                        logger.info(
                            "[%s] Form engine: upload required at step %d — attempting upload.",
                            self.NAME,
                            step,
                        )
                        upload_ok = await self.upload_resume_verified(
                            container, page, resume_path
                        )
                        if upload_ok:
                            audit.record("resume_upload", resume_path, "verified")
                            logger.info(
                                "[%s] Form engine: upload verified at step %d.",
                                self.NAME,
                                step,
                            )
                        else:
                            # CRITICAL: Upload required but failed — ABORT immediately
                            logger.error(
                                "[%s] Form engine: UPLOAD_FAILED at step %d — "
                                "aborting application. Will NOT press any more buttons.",
                                self.NAME,
                                step,
                            )
                            audit.record(
                                "upload_failed", f"step {step}", "UPLOAD_FAILED"
                            )
                            await audit.save()
                            return False
                    else:
                        logger.info(
                            "[%s] Form engine: upload already completed — skipping re-upload.",
                            self.NAME,
                        )

            # ── Fill all fields in the container ──────────────────────────
            await self.fill_form_fields_on_container(
                container, page, resume_path, form_data, llm_fn
            )
            audit.record("fields_filled", f"step {step}", "filled")

            # ── Check for form validation errors ──────────────────────────
            try:
                errors = await self.detect_form_errors_dom(page)
                if errors:
                    logger.warning(
                        "[%s] Form engine: %d errors detected via DOM: %s",
                        self.NAME,
                        len(errors),
                        errors,
                    )
                    audit.record("form_errors", str(errors), "detected")
                    await self.fill_form_fields_on_container(
                        container, page, resume_path, form_data, llm_fn
                    )
                elif vision._enabled:
                    # Fallback to Vision error checks only if page is stuck / repeating fingerprint
                    if identical_state_count >= 1:
                        errors = await vision.detect_form_errors(page)
                        if errors:
                            logger.warning(
                                "[%s] Form engine: %d errors detected via Vision: %s",
                                self.NAME,
                                len(errors),
                                errors,
                            )
                            audit.record("form_errors", str(errors), "detected")
                            await self.fill_form_fields_on_container(
                                container, page, resume_path, form_data, llm_fn
                            )
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

            # ── ZERO BLIND CLICK GUARD ─────────────────────────────────────
            click_ok, click_reason = await self._validate_page_before_click(
                page, container, resume_path
            )
            if not click_ok:
                logger.error(
                    "[%s] Form engine: pre-click validation FAILED at step %d: %s — aborting.",
                    self.NAME,
                    step,
                    click_reason,
                )
                audit.record("pre_click_guard_failed", click_reason, f"step {step}")
                if "upload_required" in click_reason:
                    # Upload specifically required and not done → treat as UPLOAD_FAILED
                    await audit.save()
                    return False
                stuck_count += 1
                if stuck_count >= 3:
                    logger.error(
                        "[%s] Form engine: pre-click guard failed 3 times. Aborting.",
                        self.NAME,
                    )
                    await audit.save()
                    return False
                await asyncio.sleep(0.5)
                continue

            # ── Try Submit button first ────────────────────────────────────
            submitted = await self.click_smart_button(container, page, "submit")
            if submitted:
                await asyncio.sleep(0.5)
                audit.record("submit_clicked", "submit_button", "clicked")
                # Verify success
                modal_type_after = await self.get_active_modal_type(page)
                if modal_type_after == "success":
                    audit.record("confirmation", "success_after_submit", "done")
                    await audit.save()
                    return True
                try:
                    if vision._enabled and await vision.detect_confirmation(page):
                        audit.record(
                            "vision_confirmation", "confirmed_after_submit", "done"
                        )
                        await audit.save()
                        return True
                except Exception as _exc:
                    logger.debug("Suppressed: %s", _exc)
                continue

            # ── Try Next/Continue button ───────────────────────────────────
            clicked_next = await self.click_smart_button(container, page, "next")
            if clicked_next:
                await asyncio.sleep(0.5)
                audit.record("next_clicked", f"step {step}", "advanced")
                continue

            # ── No button found ────────────────────────────────────────────
            logger.warning(
                "[%s] Form engine: no active button found at step %d.", self.NAME, step
            )
            stuck_count += 1
            if stuck_count >= 10:
                logger.error(
                    "[%s] Form engine: no button for 10 consecutive steps. Breaking.",
                    self.NAME,
                )
                break

        # Final body check for success keywords
        try:
            body_text = await page.inner_text("body", timeout=3000)
            if any(
                kw in body_text.lower()
                for kw in ["submitted", "success", "thank you", "received", "applied"]
            ):
                audit.record("body_confirmation", "keywords_found", "done")
                await audit.save()
                return True
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)

        audit.record(
            "form_failed", f"no confirmation after {max_steps} steps", "failed"
        )
        await audit.save()
        return False

    async def search_jobs(self, keyword: str, location: str) -> bool:
        raise NotImplementedError

    async def apply_filters(self) -> None:
        pass

    async def get_job_cards(self) -> list[Locator]:
        raise NotImplementedError

    async def get_job_id(self, card: Locator) -> str:
        raise NotImplementedError

    async def open_job(self, card: Locator) -> bool:
        raise NotImplementedError

    async def is_easy_apply(self) -> bool:
        raise NotImplementedError

    async def start_easy_apply(self) -> bool:
        raise NotImplementedError

    async def fill_form_and_submit(
        self,
        resume_path: str,
        form_data: dict,
        llm_fn: Callable[[str, str], Awaitable[str]],
    ) -> bool:
        raise NotImplementedError

    async def locate_external_apply_button(self) -> Locator | None:
        """Locates the external apply button or link on the job page."""
        if self.NAME == "LinkedIn":
            apply_btn = self.job_page.locator("button.jobs-apply-button")
            if await apply_btn.count() > 0:
                txt = await apply_btn.first.inner_text()
                if "Easy Apply" not in txt:
                    return apply_btn.first

        # Use ClickDecisionEngine to rank and select the best candidate
        try:
            from automation.click_decision import ClickDecisionEngine

            btn = await ClickDecisionEngine.rank_and_select(self.job_page, "APPLY")
            if btn:
                return btn
        except Exception as e:
            logger.debug(
                "[%s] ClickDecisionEngine failed in locate_external_apply_button: %s",
                self.NAME,
                e,
            )

        candidates = [
            "Apply on company site",
            "Apply on company website",
            "Visit Employer Website",
            "Go to Company Website",
            "Apply Now",
            "Continue Application",
            "Apply",
            "Continue",
        ]

        for cand in candidates:
            pattern = re.compile(rf"\b{re.escape(cand)}\b", re.IGNORECASE)
            btn = self.job_page.get_by_role("button", name=pattern).first
            try:
                if (
                    await btn.count() > 0
                    and await btn.is_visible()
                    and await btn.is_enabled()
                ):
                    return btn
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

            lnk = self.job_page.get_by_role("link", name=pattern).first
            try:
                if (
                    await lnk.count() > 0
                    and await lnk.is_visible()
                    and await lnk.is_enabled()
                ):
                    return lnk
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

        try:
            all_elements = self.job_page.locator(
                "button:visible, a:visible, div[role='button']:visible"
            )
            count = await all_elements.count()
            for i in range(count):
                el = all_elements.nth(i)
                try:
                    txt = (await el.inner_text()).strip()
                    if not txt:
                        continue
                    txt_lower = txt.lower()
                    for cand in candidates:
                        if cand.lower() in txt_lower:
                            return el
                except Exception:
                    continue
        except Exception as e:
            logger.debug(
                "[%s] Fallback scan for external apply button failed: %s", self.NAME, e
            )

        return None

    async def click_external_apply(self, external_btn: Locator) -> bool:
        """Clicks the external apply button and switches self.job_page to the redirected page."""
        logger.info("[%s] Clicking external apply button...", self.NAME)
        old_url = self.job_page.url
        try:
            async with self.page.context.expect_page(timeout=8000) as page_info:
                await external_btn.click()
            new_page = await page_info.value
            await new_page.wait_for_load_state("domcontentloaded")
            self.job_page = new_page
            logger.info("[%s] Switched to new tab: %s", self.NAME, self.job_page.url)
            return True
        except Exception as e:
            logger.info(
                "[%s] Click did not open a new tab: %s. Checking same tab navigation...",
                self.NAME,
                e,
            )
            try:
                await self.job_page.wait_for_load_state(
                    "domcontentloaded", timeout=8000
                )
                if self.job_page.url != old_url:
                    logger.info(
                        "[%s] Same tab navigated to: %s", self.NAME, self.job_page.url
                    )
                    return True
            except Exception as nav_err:
                logger.error(
                    "[%s] Same tab navigation check failed: %s", self.NAME, nav_err
                )

            try:
                await smart_click(self.job_page, external_btn)
                await self.job_page.wait_for_timeout(3000)
                await self.job_page.wait_for_load_state(
                    "domcontentloaded", timeout=5000
                )
                if self.job_page.url != old_url:
                    logger.info(
                        "[%s] Same tab navigated after smart_click: %s",
                        self.NAME,
                        self.job_page.url,
                    )
                    return True
            except Exception as click_err:
                logger.error(
                    "[%s] smart_click fallback failed: %s", self.NAME, click_err
                )

        return self.job_page.url != old_url

    async def detect_ats_platform(self) -> str:
        """Detects the ATS platform from URL and page DOM. Supports 20+ platforms."""
        url = self.job_page.url.lower()

        ats_mapping = {
            # Tier 1 — very common
            "workday": [
                "workdayjobs.com",
                "myworkdayjobs.com",
                "wd3.myworkdayjobs.com",
            ],
            "greenhouse": ["greenhouse.io", "boards.greenhouse.io"],
            "lever": ["lever.co", "jobs.lever.co"],
            "ashby": ["ashbyhq.com", "jobs.ashbyhq.com"],
            "successfactors": [
                "successfactors.com",
                "successfactors.eu",
                "sapsf.com",
                "sfportal",
            ],
            "oracle": ["oraclecloud.com", "fa.us2.oraclecloud.com", "oraclehcm"],
            "smartrecruiters": ["smartrecruiters.com", "jobs.smartrecruiters.com"],
            "icims": ["icims.com", "careers.icims.com"],
            "taleo": ["taleo.net", "tbe.taleo.net"],
            # Tier 2 — common
            "bamboohr": ["bamboohr.com", "app.bamboohr.com"],
            "jobvite": ["jobvite.com", "jobs.jobvite.com"],
            "recruitee": ["recruitee.com"],
            "jazzhr": ["resumatorjobs.com", "applytojob.com", "jazzhr.com"],
            "teamtailor": ["teamtailor.com"],
            "rippling": ["rippling.com"],
            "pinpoint": ["pinpointhq.com"],
            "avature": ["avature.net"],
            "eightfold": ["eightfold.ai"],
            "cornerstone": ["cornerstoneondemand.com", "csod.com"],
            "paradox": ["paradox.ai", "olivia.paradox.ai"],
            "sap": ["careers.sap.com"],
            "phenom": ["phenompeople.com", "phenom.app"],
            "workable": ["workable.com", "apply.workable.com"],
            "breezy": ["breezy.hr"],
            "personio": ["personio.de", "personio.com"],
            "comeet": ["comeet.co"],
            "hr4you": ["hr4you.de"],
        }

        for ats, patterns in ats_mapping.items():
            if any(p in url for p in patterns):
                logger.info("[%s] ATS detected via URL: %s", self.NAME, ats)
                return ats

        try:
            body_html = await self.job_page.locator("body").inner_html(timeout=2000)
            body_html_lower = body_html.lower() if body_html else ""

            dom_signatures = {
                "greenhouse": ["powered by greenhouse", "greenhouse-app", "grnhse_app"],
                "lever": ["powered by lever", "lever-app", "lever.co"],
                "ashby": ["ashbyhq", "ashby-job-app"],
                "workday": ["workday", "wd-application", "workdayjobs"],
                "smartrecruiters": ["smartrecruiters", "sr-application"],
                "icims": ["icims", "icims-apply"],
                "successfactors": ["successfactors", "sap-successfactors"],
                "taleo": ["taleo", "taleo-apply"],
                "phenom": ["phenom", "phenompeople"],
                "bamboohr": ["bamboohr", "bamboo-apply"],
                "jobvite": ["jobvite"],
                "teamtailor": ["teamtailor"],
                "eightfold": ["eightfold"],
                "cornerstone": ["cornerstoneondemand", "csod-apply"],
                "paradox": ["paradox.ai", "olivia"],
            }

            for ats, sigs in dom_signatures.items():
                if any(sig in body_html_lower for sig in sigs):
                    logger.info(
                        "[%s] ATS detected via DOM signature: %s", self.NAME, ats
                    )
                    return ats

        except Exception as e:
            logger.debug("[%s] DOM signature ATS check failed: %s", self.NAME, e)

        logger.info(
            "[%s] ATS platform: unknown (using generic AI navigation)", self.NAME
        )
        return "custom"

    async def fill_external_form_generic(
        self,
        resume_path: str,
        form_data: dict,
        llm_fn: Callable[[str, str], Awaitable[str]],
    ) -> bool:
        """Fills form fields on an external ATS page, supports multi-step forms."""
        submit_selectors = [
            "button:has-text('Submit')",
            "button:has-text('Submit application')",
            "button:has-text('Apply')",
            "button:has-text('Complete application')",
            "button:has-text('Submit Application')",
        ]
        next_selectors = [
            "button:has-text('Next')",
            "button:has-text('Continue')",
            "button:has-text('Save and Continue')",
            "button:has-text('Next step')",
            "button:has-text('Save & Continue')",
        ]
        return await self.fill_form_and_submit_generic(
            resume_path=resume_path,
            form_data=form_data,
            llm_fn=llm_fn,
            submit_selectors=submit_selectors,
            next_selectors=next_selectors,
        )

    async def verify_external_submission(self) -> bool:
        """Verifies if the external application was successfully submitted."""
        try:
            body = await self.job_page.inner_text("body", timeout=3000)
            body_l = body.lower()
            success_keywords = [
                "application submitted",
                "successfully applied",
                "your application was sent",
                "apply success",
                "thank you for applying",
                "we've received",
                "application complete",
                "confirmation",
            ]
            if any(kw in body_l for kw in success_keywords):
                return True
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)

        try:
            from automation.vision_engine import get_vision_engine

            ve = get_vision_engine()
            if ve._enabled and await ve.detect_confirmation(self.job_page):
                return True
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)

        return False

    async def _recover(self, failure_type: str) -> None:
        logger.info("[%s] Recovery triggered: %s", self.NAME, failure_type)
        try:
            if failure_type == "hidden_element":
                await self.page.evaluate("window.scrollBy(0, 200)")
            elif failure_type == "element_detached":
                await self.page.wait_for_timeout(1000)
            elif failure_type == "timeout":
                await self.page.wait_for_timeout(2000)
            elif failure_type == "page_crash":
                await self.page.reload()
        except Exception as e:
            logger.error("[%s] Recovery action failed: %s", self.NAME, e)


class LinkedInModule(BaseWebsiteModule):
    NAME = "LinkedIn"
    BASE_URL = "https://www.linkedin.com/jobs/"

    async def search_jobs(self, keyword: str, location: str) -> bool:
        try:
            import urllib.parse

            q = urllib.parse.quote(keyword)
            l = urllib.parse.quote(location)
            url = f"https://www.linkedin.com/jobs/search/?keywords={q}&location={l}&f_TPR=r604800&f_E=1%2C2"
            await self.page.goto(url, timeout=25000, wait_until="domcontentloaded")
            return True
        except Exception as e:
            logger.error("LinkedIn search failed: %s", e)
            return False

    async def get_job_cards(self) -> list[Locator]:
        locator = self.page.locator(
            "li.scaffold-layout__list-item, li.jobs-search-results-list__list-item, .job-card-container"
        )
        count = await locator.count()
        return [locator.nth(i) for i in range(count)]

    async def get_job_id(self, card: Locator) -> str:
        try:
            job_id = await card.get_attribute(
                "data-occludable-job-id"
            ) or await card.get_attribute("data-job-id")
            if job_id:
                return f"linkedin_{job_id}"
            text = await card.inner_text()
            return f"linkedin_{hash(text)}"
        except Exception:
            return ""

    async def open_job(self, card: Locator) -> bool:
        title_el = card.locator(
            "a.job-card-list__title--link, a.job-card-container__link, a.job-card-list__title, .job-card-container__link"
        ).first
        if await title_el.count() > 0:
            if await smart_click(self.page, title_el):
                try:
                    await self.page.wait_for_selector(
                        ".jobs-search__job-details, [class*='job-details']",
                        timeout=5000,
                    )
                    self.job_page = self.page
                    return True
                except Exception as _exc:
                    logger.debug("Suppressed: %s", _exc)
        if await smart_click(self.page, card):
            try:
                await self.page.wait_for_selector(
                    ".jobs-search__job-details, [class*='job-details']", timeout=5000
                )
                self.job_page = self.page
                return True
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)
        return False

    async def is_easy_apply(self) -> bool:
        apply_btn = self.job_page.locator("button.jobs-apply-button")
        if await apply_btn.count() > 0:
            text = await apply_btn.first.inner_text()
            if "Easy Apply" in text:
                return True
        return False

    async def start_easy_apply(self) -> bool:
        apply_btn = self.job_page.locator("button.jobs-apply-button")
        if await smart_click(self.job_page, apply_btn):
            try:
                await self.job_page.wait_for_selector(
                    "div.jobs-easy-apply-modal, [class*='easy-apply-modal']",
                    timeout=5000,
                )
                return True
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)
        return False

    async def _resolve_linkedin_specific_question(
        self, label: str, field_type: str, prefs: dict
    ) -> str | None:
        label_l = label.lower()

        # Sponsorship
        if "sponsor" in label_l or "visa" in label_l:
            return "Yes" if prefs.get("spons") else "No"

        # Authorization
        if "authorized" in label_l or "work in" in label_l or "legal" in label_l:
            return "Yes" if prefs.get("auth") else "No"

        # Relocation
        if "relocate" in label_l:
            return "Yes" if prefs.get("relocate") else "No"

        # Notice Period
        if "notice" in label_l:
            from services.form_service import get_form_service

            fs = get_form_service()
            if fs.is_loaded:
                val = fs.get_field("notice_period")
                if val:
                    return val
            return "Immediate"

        # Expected Salary
        if "salary" in label_l or "compensation" in label_l or "ctc" in label_l:
            from services.form_service import get_form_service

            fs = get_form_service()
            if fs.is_loaded:
                val = fs.get_field("expected_ctc") or fs.get_field("salary")
                if val:
                    return val
            return prefs.get("salary") or "Not disclosed"

        # Years of experience
        if "years of" in label_l or "experience" in label_l:
            from services.resume_intelligence import get_resume_intelligence

            resume_intel = get_resume_intelligence()
            if resume_intel.is_ready():
                profile = resume_intel.get_profile()
                if profile:
                    return "2"
            return "1"

        return None

    async def fill_form_fields_on_container(
        self,
        container: Page | FrameLocator,
        page: Page,
        resume_path: str,
        form_data: dict,
        llm_fn: Callable[[str, str], Awaitable[str]],
    ) -> None:
        from core.database import get_database

        prefs = {}
        try:
            db = get_database()
            prefs_raw = await db.get_memory("linkedin_easy_apply_preferences")
            if prefs_raw:
                prefs = json.loads(prefs_raw)
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)

        async def linkedin_llm_fn(lbl: str, ftype: str, **kwargs) -> str:
            # Check Cover Letter
            if "cover letter" in lbl.lower() or "letter of intent" in lbl.lower():
                cover_mode = prefs.get("cover_letter_mode", "Skip")
                if "auto" in cover_mode.lower():
                    from services.resume_intelligence import get_resume_intelligence

                    resume_intel = get_resume_intelligence()
                    cover_letter = await resume_intel.generate_cover_letter(
                        "Software Engineer", "LinkedIn Poster"
                    )
                    return cover_letter
                elif "saved" in cover_mode.lower():
                    from services.form_service import get_form_service

                    fs = get_form_service()
                    if fs.is_loaded:
                        val = fs.get_field("cover_letter")
                        if val:
                            return val
                return ""

            specific_ans = await self._resolve_linkedin_specific_question(
                lbl, ftype, prefs
            )
            if specific_ans is not None:
                return specific_ans
            return await llm_fn(lbl, ftype, **kwargs)

        await super().fill_form_fields_on_container(
            container, page, resume_path, form_data, linkedin_llm_fn
        )

    async def fill_form_and_submit(
        self,
        resume_path: str,
        form_data: dict,
        llm_fn: Callable[[str, str], Awaitable[str]],
    ) -> bool:
        max_steps = 15
        step = 0
        page = self.job_page
        last_step_fingerprint = ""
        fingerprint_repeat_count = 0

        while step < max_steps:
            step += 1
            modal = page.locator(
                "div.jobs-easy-apply-modal, [class*='easy-apply-modal']"
            )
            if await modal.count() == 0:
                break

            success_msg = page.locator(
                ".artdeco-inline-feedback--success, :has-text('Application submitted')"
            )
            if await success_msg.count() > 0:
                logger.info("LinkedIn: Success confirmation detected!")
                dismiss_btn = page.locator(
                    "button:has-text('Done'), button:has-text('Dismiss')"
                )
                if await dismiss_btn.count() > 0:
                    await smart_click(page, dismiss_btn)
                return True

            # Check for assessment requests on the page
            page_text = await page.inner_text("body")
            if any(
                kw in page_text.lower()
                for kw in [
                    "take an assessment",
                    "complete assessment",
                    "test required",
                    "online assessment",
                ]
            ):
                logger.warning("LinkedIn: Assessment required. Skipping application.")
                break

            modal_container = modal.first

            # Form stuck protection using state fingerprint
            try:
                curr_fingerprint = await modal_container.inner_text()
                if curr_fingerprint == last_step_fingerprint:
                    fingerprint_repeat_count += 1
                else:
                    fingerprint_repeat_count = 0
                    last_step_fingerprint = curr_fingerprint

                if fingerprint_repeat_count >= 3:
                    logger.warning("LinkedIn: Stuck on the same page. Closing modal.")
                    break
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

            await self.fill_form_fields_on_container(
                modal_container, page, resume_path, form_data, llm_fn
            )

            submitted = await self.click_smart_button(modal_container, page, "submit")
            if submitted:
                logger.info(
                    "LinkedIn: Submit button clicked. Verifying multi-signal success..."
                )
                await page.wait_for_timeout(2000)

                # Check 1: Success message/badge inside the modal
                success_msg = page.locator(
                    ".artdeco-inline-feedback--success, :has-text('Application submitted'), [class*='success']"
                ).first
                if await success_msg.count() > 0:
                    logger.info(
                        "LinkedIn: Success confirmation detected via success badge!"
                    )
                    dismiss_btn = page.locator(
                        "button:has-text('Done'), button:has-text('Dismiss'), button[aria-label='Dismiss']"
                    ).first
                    if await dismiss_btn.count() > 0:
                        await smart_click(page, dismiss_btn)
                    return True

                # Check 2: Modal closed/disappeared
                if await modal.count() == 0 or not await modal.first.is_visible():
                    logger.info(
                        "LinkedIn: Modal closed after submission. Checking main button badge..."
                    )
                    apply_btn = page.locator("button.jobs-apply-button")
                    if await apply_btn.count() > 0:
                        btn_text = await apply_btn.first.inner_text()
                        if "Applied" in btn_text or "applied" in btn_text.lower():
                            logger.info(
                                "LinkedIn: Success confirmed via 'Applied' badge!"
                            )
                            return True

                    # Verify via body confirmation keywords
                    body_text = await page.inner_text("body")
                    if any(
                        kw in body_text.lower()
                        for kw in [
                            "applied",
                            "submitted",
                            "application sent",
                            "thank you",
                        ]
                    ):
                        logger.info("LinkedIn: Success confirmed via body keywords!")
                        return True

                # Check 3: If Done or Dismiss button appeared inside the modal
                dismiss_btn = page.locator(
                    "button:has-text('Done'), button:has-text('Dismiss'), button[aria-label='Dismiss']"
                ).first
                if await dismiss_btn.count() > 0 and await dismiss_btn.is_visible():
                    logger.info(
                        "LinkedIn: Done/Dismiss button found. Clicking to complete..."
                    )
                    await smart_click(page, dismiss_btn)
                    return True

                continue

            clicked_next = await self.click_smart_button(modal_container, page, "next")
            if clicked_next:
                await page.wait_for_timeout(500)
                continue

        # Close the modal if we didn't succeed
        logger.warning("LinkedIn: Form modal incomplete. Discarding application.")
        close_btn = page.locator("button[aria-label='Dismiss']").first
        if await close_btn.count() > 0:
            await smart_click(page, close_btn)
            discard_btn = page.locator("button:has-text('Discard')").first
            if await discard_btn.count() > 0:
                await smart_click(page, discard_btn)
        return False


class NaukriModule(BaseWebsiteModule):
    NAME = "Naukri"
    BASE_URL = "https://www.naukri.com/"

    async def search_jobs(self, keyword: str, location: str) -> bool:
        try:
            kw_part = keyword.lower().replace(" ", "-")
            loc_part = location.lower().replace(" ", "-")
            url = f"https://www.naukri.com/{kw_part}-jobs-in-{loc_part}"
            await self.page.goto(url, timeout=25000, wait_until="domcontentloaded")
            return True
        except Exception as e:
            logger.error("Naukri search failed: %s", e)
            return False

    async def get_job_cards(self) -> list[Locator]:
        locator = self.page.locator("article.jobTuple, div.cust-job-tuple")
        count = await locator.count()
        return [locator.nth(i) for i in range(count)]

    async def get_job_id(self, card: Locator) -> str:
        try:
            val = await card.get_attribute("data-job-id")
            if val:
                return f"naukri_{val}"
            txt = await card.inner_text()
            return f"naukri_{hash(txt)}"
        except Exception:
            return ""

    async def open_job(self, card: Locator) -> bool:
        title_el = card.locator("a.title, a.job-title").first
        try:
            async with self.page.context.expect_page(timeout=5000) as page_info:
                if not await smart_click(self.page, title_el):
                    return False
            self.job_page = await page_info.value
            await self.job_page.wait_for_load_state("domcontentloaded")
            return True
        except Exception:
            return False

    async def is_easy_apply(self) -> bool:
        apply_btn = self.job_page.locator(
            "button#apply-button, button.apply-button, a.apply-button"
        )
        return await apply_btn.count() > 0

    async def start_easy_apply(self) -> bool:
        apply_btn = self.job_page.locator(
            "button#apply-button, button.apply-button, a.apply-button"
        ).first
        return await smart_click(self.job_page, apply_btn)

    async def fill_form_and_submit(
        self,
        resume_path: str,
        form_data: dict,
        llm_fn: Callable[[str, str], Awaitable[str]],
    ) -> bool:
        return await self.fill_form_and_submit_generic(
            resume_path=resume_path,
            form_data=form_data,
            llm_fn=llm_fn,
            submit_selectors=[
                "button:has-text('Submit')",
                "button:has-text('Apply')",
                "#apply-button",
            ],
            next_selectors=["button:has-text('Next')", "button:has-text('Continue')"],
        )


class IndeedModule(BaseWebsiteModule):
    NAME = "Indeed"
    BASE_URL = "https://in.indeed.com/"

    async def search_jobs(self, keyword: str, location: str) -> bool:
        try:
            import urllib.parse

            q = urllib.parse.quote(keyword)
            l = urllib.parse.quote(location)
            url = f"https://in.indeed.com/jobs?q={q}&l={l}&fromage=7"
            await self.page.goto(url, timeout=25000, wait_until="domcontentloaded")
            return True
        except Exception as e:
            logger.error("Indeed search failed: %s", e)
            return False

    async def get_job_cards(self) -> list[Locator]:
        locator = self.page.locator("div.job_seen_beacon, td.resultContent")
        count = await locator.count()
        return [locator.nth(i) for i in range(count)]

    async def get_job_id(self, card: Locator) -> str:
        try:
            txt = await card.inner_text()
            return f"indeed_{hash(txt)}"
        except Exception:
            return ""

    async def open_job(self, card: Locator) -> bool:
        title_el = card.locator("a[id^='job_'], h2.jobTitle a, .jcs-JobTitle").first
        try:
            async with self.page.context.expect_page(timeout=3000) as page_info:
                if not await smart_click(self.page, title_el):
                    return False
            self.job_page = await page_info.value
            await self.job_page.wait_for_load_state("domcontentloaded")
            return True
        except Exception:
            self.job_page = self.page
            if await smart_click(self.page, title_el):
                try:
                    await self.page.wait_for_selector(
                        "#jobsearch-ViewjobPaneWrapper, .jobsearch-RightPane",
                        timeout=5000,
                    )
                    return True
                except Exception as _exc:
                    logger.debug("Suppressed: %s", _exc)
            return False

    async def is_easy_apply(self) -> bool:
        apply_btn = self.job_page.locator(
            "button.ia-IndeedApplyButton, .indeed-apply-button"
        )
        return await apply_btn.count() > 0

    async def start_easy_apply(self) -> bool:
        apply_btn = self.job_page.locator(
            "button.ia-IndeedApplyButton, .indeed-apply-button"
        ).first
        return await smart_click(self.job_page, apply_btn)

    async def fill_form_and_submit(
        self,
        resume_path: str,
        form_data: dict,
        llm_fn: Callable[[str, str], Awaitable[str]],
    ) -> bool:
        return await self.fill_form_and_submit_generic(
            resume_path=resume_path,
            form_data=form_data,
            llm_fn=llm_fn,
            submit_selectors=[
                "button:has-text('Submit your application')",
                "button:has-text('Submit')",
                "button:has-text('Apply')",
            ],
            next_selectors=["button:has-text('Next')", "button:has-text('Continue')"],
        )


class FounditModule(BaseWebsiteModule):
    NAME = "Foundit"
    BASE_URL = "https://www.foundit.in/"

    async def search_jobs(self, keyword: str, location: str) -> bool:
        try:
            import urllib.parse

            q = urllib.parse.quote(keyword)
            l = urllib.parse.quote(location)
            url = f"https://www.foundit.in/srp/results?query={q}&locations={l}"
            await self.page.goto(url, timeout=25000, wait_until="domcontentloaded")
            return True
        except Exception as e:
            logger.error("Foundit search failed: %s", e)
            return False

    async def get_job_cards(self) -> list[Locator]:
        locator = self.page.locator("div.cardContent, div.job-tuple")
        count = await locator.count()
        return [locator.nth(i) for i in range(count)]

    async def get_job_id(self, card: Locator) -> str:
        try:
            txt = await card.inner_text()
            return f"foundit_{hash(txt)}"
        except Exception:
            return ""

    async def open_job(self, card: Locator) -> bool:
        title_el = card.locator("a.job-title, div.jobTitle a").first
        try:
            async with self.page.context.expect_page(timeout=5000) as page_info:
                if not await smart_click(self.page, title_el):
                    return False
            self.job_page = await page_info.value
            await self.job_page.wait_for_load_state("domcontentloaded")
            return True
        except Exception:
            return False

    async def is_easy_apply(self) -> bool:
        apply_btn = self.job_page.locator("button:has-text('Apply'), a.apply-btn")
        return await apply_btn.count() > 0

    async def start_easy_apply(self) -> bool:
        apply_btn = self.job_page.locator("button:has-text('Apply'), a.apply-btn").first
        return await smart_click(self.job_page, apply_btn)

    async def fill_form_and_submit(
        self,
        resume_path: str,
        form_data: dict,
        llm_fn: Callable[[str, str], Awaitable[str]],
    ) -> bool:
        return await self.fill_form_and_submit_generic(
            resume_path=resume_path,
            form_data=form_data,
            llm_fn=llm_fn,
            submit_selectors=["button:has-text('Submit')", "button:has-text('Apply')"],
            next_selectors=["button:has-text('Next')", "button:has-text('Continue')"],
        )


class WellfoundModule(BaseWebsiteModule):
    NAME = "Wellfound"
    BASE_URL = "https://wellfound.com/jobs"

    async def search_jobs(self, keyword: str, location: str) -> bool:
        try:
            await self.page.goto(
                self.BASE_URL, timeout=25000, wait_until="domcontentloaded"
            )
            return True
        except Exception as e:
            logger.error("Wellfound navigation failed: %s", e)
            return False

    async def get_job_cards(self) -> list[Locator]:
        locator = self.page.locator("[class*='JobCard'], [data-test='JobResult']")
        count = await locator.count()
        return [locator.nth(i) for i in range(count)]

    async def get_job_id(self, card: Locator) -> str:
        try:
            txt = await card.inner_text()
            return f"wellfound_{hash(txt)}"
        except Exception:
            return ""

    async def open_job(self, card: Locator) -> bool:
        self.job_page = self.page
        return await smart_click(self.page, card)

    async def is_easy_apply(self) -> bool:
        apply_btn = self.job_page.locator(
            "button:has-text('Apply'), [class*='ApplyButton']"
        )
        return await apply_btn.count() > 0

    async def start_easy_apply(self) -> bool:
        apply_btn = self.job_page.locator("button:has-text('Apply')").first
        return await smart_click(self.job_page, apply_btn)

    async def fill_form_and_submit(
        self,
        resume_path: str,
        form_data: dict,
        llm_fn: Callable[[str, str], Awaitable[str]],
    ) -> bool:
        return await self.fill_form_and_submit_generic(
            resume_path=resume_path,
            form_data=form_data,
            llm_fn=llm_fn,
            submit_selectors=[
                "button:has-text('Submit Application')",
                "button:has-text('Submit')",
            ],
            next_selectors=["button:has-text('Next')", "button:has-text('Continue')"],
        )


class InstahyreModule(BaseWebsiteModule):
    NAME = "Instahyre"
    BASE_URL = "https://www.instahyre.com/candidate/opportunities/"

    async def search_jobs(self, keyword: str, location: str) -> bool:
        try:
            await self.page.goto(
                self.BASE_URL, timeout=25000, wait_until="domcontentloaded"
            )
            return True
        except Exception as e:
            logger.error("Instahyre navigation failed: %s", e)
            return False

    async def get_job_cards(self) -> list[Locator]:
        locator = self.page.locator(".job-card, .job-description, [class*='job-card']")
        count = await locator.count()
        return [locator.nth(i) for i in range(count)]

    async def get_job_id(self, card: Locator) -> str:
        try:
            txt = await card.inner_text()
            return f"instahyre_{hash(txt)}"
        except Exception:
            return ""

    async def open_job(self, card: Locator) -> bool:
        self.job_page = self.page
        return await smart_click(self.page, card)

    async def is_easy_apply(self) -> bool:
        apply_btn = self.job_page.locator("button:has-text('Apply'), .apply-button")
        return await apply_btn.count() > 0

    async def start_easy_apply(self) -> bool:
        apply_btn = self.job_page.locator(
            "button:has-text('Apply'), .apply-button"
        ).first
        return await smart_click(self.job_page, apply_btn)

    async def fill_form_and_submit(
        self,
        resume_path: str,
        form_data: dict,
        llm_fn: Callable[[str, str], Awaitable[str]],
    ) -> bool:
        return await self.fill_form_and_submit_generic(
            resume_path=resume_path,
            form_data=form_data,
            llm_fn=llm_fn,
            submit_selectors=["button:has-text('Submit')", "button:has-text('Apply')"],
            next_selectors=["button:has-text('Next')", "button:has-text('Continue')"],
        )


class GlassdoorModule(BaseWebsiteModule):
    NAME = "Glassdoor"
    BASE_URL = "https://www.glassdoor.co.in/Job/index.htm"

    async def search_jobs(self, keyword: str, location: str) -> bool:
        try:
            import urllib.parse

            q = urllib.parse.quote(keyword)
            url = f"https://www.glassdoor.co.in/Job/jobs.htm?sc.keyword={q}"
            await self.page.goto(url, timeout=25000, wait_until="domcontentloaded")
            return True
        except Exception as e:
            logger.error("Glassdoor search failed: %s", e)
            return False

    async def get_job_cards(self) -> list[Locator]:
        locator = self.page.locator("li[data-test='jobListing']")
        count = await locator.count()
        return [locator.nth(i) for i in range(count)]

    async def get_job_id(self, card: Locator) -> str:
        try:
            txt = await card.inner_text()
            return f"glassdoor_{hash(txt)}"
        except Exception:
            return ""

    async def open_job(self, card: Locator) -> bool:
        title_el = card.locator("a[data-test='job-title']").first
        if await smart_click(self.page, title_el):
            self.job_page = self.page
            try:
                await self.page.wait_for_selector("[class*='JobDetails']", timeout=5000)
                return True
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)
        return False

    async def is_easy_apply(self) -> bool:
        apply_btn = self.job_page.locator("button[data-test='easy-apply']")
        return await apply_btn.count() > 0

    async def start_easy_apply(self) -> bool:
        apply_btn = self.job_page.locator("button[data-test='easy-apply']").first
        return await smart_click(self.job_page, apply_btn)

    async def fill_form_and_submit(
        self,
        resume_path: str,
        form_data: dict,
        llm_fn: Callable[[str, str], Awaitable[str]],
    ) -> bool:
        return await self.fill_form_and_submit_generic(
            resume_path=resume_path,
            form_data=form_data,
            llm_fn=llm_fn,
            submit_selectors=[
                "button:has-text('Submit Application')",
                "button:has-text('Submit')",
            ],
            next_selectors=["button:has-text('Next')", "button:has-text('Continue')"],
        )


# Helper map of strategies/modules
MODULES = {
    "linkedin": LinkedInModule,
    "naukri": NaukriModule,
    "indeed": IndeedModule,
    "foundit": FounditModule,
    "wellfound": WellfoundModule,
    "instahyre": InstahyreModule,
    "glassdoor": GlassdoorModule,
}


def get_website_module(site_name: str, page: Page) -> BaseWebsiteModule | None:
    cls = MODULES.get(site_name.lower())
    return cls(page) if cls else None
