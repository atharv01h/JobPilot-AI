"""
Browser manager — orchestrates Browser-Use Agent runs with NVIDIA NIM LLM.

Architecture:
  - BrowserManager is a thin orchestrator — it does NOT own browser state.
  - All browser connections go through BrowserSessionPool (single session).
  - All CDP/process management is delegated to cdp_connector.py.
  - The watchdog monitors for inactivity and triggers session recovery.

Monkeypatching:
  - AgentOutput.model_validate_json is patched to handle malformed LLM JSON.
  - Agent.__init__ / Agent.step / Agent.multi_act are patched for Anti-Stall
    and Fast-Action-Mode to prevent thinking/wait loops.
"""

from __future__ import annotations

import asyncio
import re
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any

from config.constants import (
    BROWSER_TIMEOUT,
    CDP_PORT,
    WATCHDOG_INACTIVITY_S,
)
from config.settings import get_settings
from core.logger import get_logger

logger = get_logger(__name__)

# ── Profile directory (for Chromium fallback) ─────────────────────────────────
_PROJECT_ROOT = Path(__file__).parent.parent
PROFILE_DIR = _PROJECT_ROOT / "browser_profile"
PROFILE_DIR.mkdir(parents=True, exist_ok=True)

_MAX_LOGIN_RETRIES = 3

# ── Watchdog state (thread-safe) ─────────────────────────────────────────────
_watchdog_lock = threading.Lock()
_watchdog_thread: threading.Thread | None = None
_watchdog_stop = threading.Event()
_watchdog_active = threading.Event()  # set() when a CDP operation is in progress


def _update_activity() -> None:
    from automation.browser_health import record_progress

    record_progress("browser_manager_update")


def _dump_stack_traces() -> None:
    logger.error("=== WATCHDOG TRIGGERED: STACK TRACE DUMP ===")
    for thread_id, frame in sys._current_frames().items():
        logger.error("\n--- Thread ID: %d ---", thread_id)
        logger.error("".join(traceback.format_stack(frame)))
    logger.error("=== END WATCHDOG DUMP ===")


def _start_watchdog() -> None:
    global _watchdog_thread
    with _watchdog_lock:
        if _watchdog_thread is not None and _watchdog_thread.is_alive():
            return

        watchdog_state = {
            "last_counter": -1,
            "stall_count": 0,
            "last_check_time": time.time(),
        }

        def _loop() -> None:
            while not _watchdog_stop.is_set():
                _watchdog_stop.wait(timeout=5.0)  # check every 5 seconds
                if _watchdog_stop.is_set():
                    break
                if not _watchdog_active.is_set():
                    watchdog_state["stall_count"] = 0
                    continue

                import automation.browser_health as bh

                current_counter = bh.progress_counter.value
                current_state = bh.get_execution_state()

                if current_counter != watchdog_state["last_counter"]:
                    watchdog_state["last_counter"] = current_counter
                    watchdog_state["stall_count"] = 0
                    watchdog_state["last_check_time"] = time.time()
                    continue

                elapsed = time.time() - watchdog_state["last_check_time"]
                if elapsed >= WATCHDOG_INACTIVITY_S:
                    watchdog_state["last_check_time"] = time.time()
                    watchdog_state["stall_count"] += 1
                    stall_count = watchdog_state["stall_count"]

                    logger.warning(
                        "Watchdog: Stall detected (stall_count=%d, counter=%d, state=%s)",
                        stall_count,
                        current_counter,
                        current_state,
                    )

                    if stall_count == 1:
                        logger.warning("Watchdog: First detection - Warning logged.")
                    elif stall_count == 2:
                        logger.warning(
                            "Watchdog: Second detection - Capturing diagnostics."
                        )
                        try:
                            _dump_stack_traces()
                        except Exception as _exc:
                            logger.debug("Suppressed: %s", _exc)
                        try:
                            if bh._active_orchestrator and bh._active_orchestrator.page:
                                loop = asyncio.get_event_loop()
                                if loop.is_running():
                                    asyncio.run_coroutine_threadsafe(
                                        bh._active_orchestrator.page.screenshot(
                                            path="logs/watchdog_diagnostic.png"
                                        ),
                                        loop,
                                    )
                        except Exception as screenshot_err:
                            logger.debug(
                                "Watchdog: Screenshot diagnostic capture failed: %s",
                                screenshot_err,
                            )

                    else:
                        recovery_level = stall_count - 2
                        logger.error(
                            "Watchdog: Progressive Recovery Escalation - Level %d",
                            recovery_level,
                        )

                        if recovery_level > 10:
                            logger.critical(
                                "Watchdog: Maximum recovery level exceeded! Force cancelling task and stopping watchdog..."
                            )
                            if bh._active_task and not bh._active_task.done():
                                loop = asyncio.get_event_loop()
                                if loop.is_running():
                                    loop.call_soon_threadsafe(bh._active_task.cancel)
                            # Stop the watchdog to prevent infinite escalation
                            _watchdog_stop.set()
                            return
                        else:
                            if bh._active_orchestrator:
                                loop = asyncio.get_event_loop()
                                if loop.is_running():
                                    asyncio.run_coroutine_threadsafe(
                                        bh._active_orchestrator.trigger_recovery_level(
                                            recovery_level
                                        ),
                                        loop,
                                    )

        _watchdog_thread = threading.Thread(
            target=_loop, daemon=True, name="BrowserWatchdog"
        )
        _watchdog_thread.start()
        logger.info("Browser watchdog started (timeout=%ds).", WATCHDOG_INACTIVITY_S)


def log_active(level: str, msg: str, *args: Any) -> None:
    """Log a message and reset the watchdog timer."""
    _update_activity()
    full_msg = f"LOG: {msg}"
    if level == "info":
        logger.info(full_msg, *args)
    elif level == "warning":
        logger.warning(full_msg, *args)
    elif level == "error":
        logger.error(full_msg, *args)
    else:
        logger.debug(full_msg, *args)


class BrowserManager:
    """
    Orchestrator for browser-based automation tasks.
    Uses SmartAIOrchestrator to delegate to site-specific modules.
    """

    def __init__(self) -> None:
        logger.info("BrowserManager initialized (profile: %s).", PROFILE_DIR)

    async def run_job_application(self, job: Job) -> str:
        """
        Execute the job application flow for a single job using SmartAIOrchestrator.
        """
        from automation.browser_health import (
            get_app_health_monitor,
            register_active_orchestrator,
            unregister_active_orchestrator,
        )
        from automation.browser_session_pool import get_browser_session_pool
        from automation.smart_ai import SmartAIOrchestrator
        from services.session_manager import get_session_manager

        sm = get_session_manager()
        sm.is_agent_running = True

        pool = get_browser_session_pool()

        try:
            _watchdog_active.set()
            _update_activity()

            # Start App Health Monitor
            get_app_health_monitor().start()

            # Get resume path and profile data
            settings = get_settings()
            resume_path = settings.resume_path

            # Read profile data from profile config via ServiceRegistry
            from core.service_registry import ServiceRegistry

            profile_service = ServiceRegistry.get("ProfileService")
            profile = await profile_service.get_profile() if profile_service else None
            profile_dict = profile.model_dump() if profile else {}

            # Use context manager for proper lifecycle management
            async with pool.context() as context:
                pages = context.pages
                page = pages[0] if pages else await context.new_page()

                orchestrator = SmartAIOrchestrator(page)
                register_active_orchestrator(orchestrator, asyncio.current_task())

                result = await asyncio.wait_for(
                    orchestrator.apply_to_job(job, resume_path, profile_dict),
                    timeout=BROWSER_TIMEOUT,
                )

                _watchdog_active.clear()
                return result
        except asyncio.CancelledError:
            logger.warning(
                "Job application task was CANCELLED — Brave session preserved."
            )
            return "CANCELLED"
        except asyncio.TimeoutError:
            logger.warning(
                "Job application task TIMEOUT after %ds — Brave session preserved.",
                BROWSER_TIMEOUT,
            )
            return "TIMEOUT"
        except Exception as exc:
            err_str = str(exc).lower()
            logger.error("Job application error: %s", exc)
            if any(
                kw in err_str
                for kw in [
                    "browser has been closed",
                    "context or browser has been closed",
                    "target closed",
                    "connection refused",
                    "pipe closed",
                ]
            ):
                logger.error(
                    "Unrecoverable browser error during application — force-invalidating session."
                )
                await pool.force_invalidate()
            return "FAILED"
        finally:
            _watchdog_active.clear()
            unregister_active_orchestrator()
            get_app_health_monitor().stop()
            sm.is_agent_running = False

    async def retrieve_gmail_otp_automatic(self, site_name: str) -> str | None:
        """
        Automatically retrieve verification email OTP or links from Gmail.
        Opens a background page, navigates to Gmail, searches, and extracts the code/link.
        """
        logger.info(
            "retrieve_gmail_otp_automatic: Attempting Gmail OTP retrieval for %s...",
            site_name,
        )
        from automation.browser_session_pool import get_browser_session_pool

        pool = get_browser_session_pool()

        async with pool.page() as page:
            try:
                # Navigate to Gmail search
                await page.goto(
                    "https://mail.google.com/mail/u/0/#search/" + site_name,
                    timeout=20000,
                )
                await asyncio.sleep(6.0)  # Wait for load and search results

                # Check if we are logged in to Gmail
                if "signin" in page.url or "accounts.google" in page.url:
                    logger.warning(
                        "retrieve_gmail_otp_automatic: Gmail is not logged in!"
                    )
                    return None

                # Locate email list rows (Gmail matches tr.zA or div.zA)
                rows = page.locator("tr.zA")
                row_count = await rows.count()
                if row_count == 0:
                    rows = page.locator("div.zA")
                    row_count = await rows.count()

                logger.info(
                    "retrieve_gmail_otp_automatic: Found %d email rows in list.",
                    row_count,
                )

                # Check the first few rows (newest first)
                for i in range(min(5, row_count)):
                    row = rows.nth(i)
                    text = await row.inner_text()
                    logger.debug("Gmail row %d text: %s", i, text[:150])

                    # Check if it looks like a verification/OTP email
                    keywords = [
                        "verification",
                        "code",
                        "otp",
                        "confirm",
                        "verify",
                        "one-time",
                        "account",
                    ]
                    if any(k in text.lower() for k in keywords):
                        logger.info(
                            "retrieve_gmail_otp_automatic: Found matching email row: %s",
                            text[:100],
                        )
                        # Click the email row to open it
                        await row.click()
                        await asyncio.sleep(4.0)  # Wait for email to open

                        # Extract body text
                        body_el = page.locator(
                            ".a3s"
                        )  # Gmail mail body container selector
                        if await body_el.count() == 0:
                            body_el = page.locator("div[role='main']")

                        body_text = await body_el.inner_text()
                        logger.debug("Opened email body: %s", body_text[:300])

                        # Search for numeric OTP (typically 4-8 digits)
                        otp_match = re.search(r"\b(\d{4,8})\b", body_text)
                        if otp_match:
                            code = otp_match.group(1)
                            logger.info(
                                "retrieve_gmail_otp_automatic: Extracted OTP code: %s",
                                code,
                            )
                            # Go back to search list
                            await page.goto(
                                "https://mail.google.com/mail/u/0/#search/" + site_name,
                                timeout=10000,
                            )
                            return code

                        # Also look for links like verification URLs
                        link_loc = page.locator(
                            "a:has-text('verify'), a:has-text('confirm'), a:has-text('activate'), a:has-text('click here')"
                        )
                        link_count = await link_loc.count()
                        if link_count > 0:
                            # Click the first link (will open in a new tab)
                            async with page.context.expect_page() as new_page_info:
                                await link_loc.first.click()
                            new_tab = await new_page_info.value
                            await new_tab.wait_for_load_state()
                            logger.info(
                                "retrieve_gmail_otp_automatic: Clicked verification link in new tab. URL: %s",
                                new_tab.url,
                            )
                            await asyncio.sleep(4.0)
                            await new_tab.close()
                            return "VERIFIED_LINK"

                        # Fallback regex search for link
                        url_match = re.search(
                            r'https?://[^\s"\'>]+(?:verify|confirm|activate)[^\s"\'>]+',
                            body_text,
                        )
                        if url_match:
                            verify_url = url_match.group(0)
                            logger.info(
                                "retrieve_gmail_otp_automatic: Found verification URL in text: %s",
                                verify_url,
                            )
                            new_tab = await page.context.new_page()
                            await new_tab.goto(verify_url)
                            await asyncio.sleep(4.0)
                            await new_tab.close()
                            return "VERIFIED_LINK"

                        break  # Checked the most relevant email
                logger.warning(
                    "retrieve_gmail_otp_automatic: No OTP or link found in emails."
                )
            except Exception as e:
                logger.error("retrieve_gmail_otp_automatic error: %s", e)
            return None

    # ── Session utilities ─────────────────────────────────────────────────────

    @staticmethod
    def get_profile_path() -> str:
        return str(PROFILE_DIR)

    @staticmethod
    def clear_sessions() -> None:
        """Delete saved browser profile (forces re-login)."""
        import shutil

        if PROFILE_DIR.exists():
            try:
                shutil.rmtree(PROFILE_DIR)
            except Exception as exc:
                logger.warning("Failed to delete browser_profile: %s", exc)
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            from services.session_manager import get_session_manager

            get_session_manager().clear_status_cache()
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)
        logger.info("Browser sessions cleared.")

    @staticmethod
    async def open_login_session_async(site_url: str) -> None:
        """
        Open a manual browser window for the user to log in.
        Connects via Brave CDP if available, otherwise uses Chromium.
        """
        from pathlib import Path as _Path

        from playwright.async_api import async_playwright

        from automation.cdp_connector import (
            connect_cdp,
            ensure_brave_debug_ready,
            is_cdp_port_open,
        )
        from config.constants import BRAVE_EXE_PATH

        logger.info("Opening manual login session: %s", site_url)

        async with async_playwright() as p:
            browser = None
            context = None
            try:
                if _Path(BRAVE_EXE_PATH).exists():
                    brave_ready = await ensure_brave_debug_ready(CDP_PORT)
                    if brave_ready and await asyncio.to_thread(
                        is_cdp_port_open, CDP_PORT
                    ):
                        try:
                            browser = await connect_cdp(p, CDP_PORT)
                            page = await browser.new_page()
                            await page.goto(site_url, timeout=30000)
                            logger.info(
                                "Opened %s in Brave — waiting for tab closure.",
                                site_url,
                            )
                            try:
                                await page.wait_for_event("close", timeout=0)
                            except Exception as _exc:
                                logger.debug("Suppressed: %s", _exc)
                            logger.info("Brave login tab closed.")
                            return
                        except Exception as cdp_err:
                            logger.warning(
                                "CDP login window failed: %s — falling back to Chromium.",
                                cdp_err,
                            )

                # Chromium fallback
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=str(PROFILE_DIR),
                    headless=False,
                    ignore_default_args=["--enable-automation"],
                    args=[
                        "--start-maximized",
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                    ],
                )
                page = await context.new_page()
                await page.goto(site_url, timeout=30000)
                logger.info(
                    "Opened %s in Chromium — waiting for window closure.", site_url
                )
                try:
                    await context.wait_for_event("close", timeout=0)
                except Exception as _exc:
                    logger.debug("Suppressed: %s", _exc)
                logger.info("Chromium login window closed.")
            except Exception as exc:
                logger.error("open_login_session_async error: %s", exc)
            finally:
                if context:
                    try:
                        await context.close()
                    except Exception as _exc:
                        logger.debug("Suppressed: %s", _exc)
                if browser:
                    try:
                        await browser.close()
                    except Exception as _exc:
                        logger.debug("Suppressed: %s", _exc)

    @staticmethod
    def open_login_session(site_url: str) -> None:
        """Synchronous wrapper — runs login session in a daemon thread."""
        t = threading.Thread(
            target=lambda: asyncio.run(
                BrowserManager.open_login_session_async(site_url)
            ),
            daemon=True,
            name="LoginSession",
        )
        t.start()
        logger.info("Manual login session thread started: %s", site_url)


# ── Singleton ─────────────────────────────────────────────────────────────────

_browser_manager: BrowserManager | None = None


def get_browser_manager() -> BrowserManager:
    global _browser_manager
    if _browser_manager is None:
        _browser_manager = BrowserManager()
        try:
            from core.service_registry import ServiceRegistry

            ServiceRegistry.register("BrowserManager", _browser_manager)
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)
    return _browser_manager
