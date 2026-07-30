"""
Scheduler service using APScheduler.
Supports: manual, hourly, daily, weekly search runs.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from core.logger import get_logger

logger = get_logger(__name__)

# Shared event loop registered by the App at startup
_app_loop: asyncio.AbstractEventLoop | None = None


def set_app_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Register the app's shared async event loop for scheduler callbacks."""
    global _app_loop
    _app_loop = loop


try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    _APS_AVAILABLE = True
except ImportError:
    _APS_AVAILABLE = False
    logger.warning("APScheduler not available — scheduler disabled")


class SchedulerService:
    """Manages automated job search scheduling."""

    JOB_ID = "auto_job_search"

    def __init__(self) -> None:
        self._scheduler = BackgroundScheduler() if _APS_AVAILABLE else None
        self._callback: Callable | None = None
        self._running = False

    def set_callback(self, callback: Callable) -> None:
        """Set the function to call when the scheduler fires."""
        self._callback = callback

    def start(self) -> None:
        if self._scheduler and not self._running:
            self._scheduler.start()
            self._running = True
            logger.info("Scheduler started")

    def stop(self) -> None:
        if self._scheduler and self._running:
            self._scheduler.shutdown(wait=False)
            self._running = False
            logger.info("Scheduler stopped")

    def apply_interval(self, interval: str | int) -> None:
        """
        interval: "Manual" | "Every Hour" | "Daily" | "Weekly" or minutes as int/string
        """
        if not _APS_AVAILABLE or not self._scheduler:
            logger.warning("Scheduler not available")
            return

        # Remove existing job
        try:
            self._scheduler.remove_job(self.JOB_ID)
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)

        if interval == "Manual" or not self._callback:
            logger.info("Scheduler set to Manual (no auto-run)")
            return

        trigger = None
        try:
            minutes = int(interval)
            trigger = IntervalTrigger(minutes=minutes)
            logger.info("Scheduler set to run every %d minutes", minutes)
        except ValueError:
            trigger_map = {
                "Every Hour": IntervalTrigger(hours=1),
                "Daily": CronTrigger(hour=9, minute=0),
                "Weekly": CronTrigger(day_of_week="mon", hour=9, minute=0),
            }
            trigger = trigger_map.get(interval)
            if trigger:
                logger.info("Scheduler set to preset: %s", interval)

        if trigger:
            self._scheduler.add_job(
                self._fire,
                trigger=trigger,
                id=self.JOB_ID,
                replace_existing=True,
            )

    def _fire(self) -> None:
        """Called by APScheduler — submits callback to the app's shared event loop."""
        if not self._callback:
            return
        if _app_loop and _app_loop.is_running():
            # Submit to the existing running loop (avoids Playwright loop conflicts)
            asyncio.run_coroutine_threadsafe(self._callback(), _app_loop)
        else:
            # Fallback: create a temporary loop (only if no shared loop is available)
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(self._callback())
                loop.close()
            except Exception as exc:
                logger.error("Scheduler callback error (fallback loop): %s", exc)

    def run_now(self) -> None:
        """Trigger an immediate search run."""
        self._fire()

    @property
    def is_running(self) -> bool:
        return self._running


# ── Singleton ─────────────────────────────────────────────────────────────────

_scheduler: SchedulerService | None = None


def get_scheduler() -> SchedulerService:
    global _scheduler
    if _scheduler is None:
        _scheduler = SchedulerService()
    return _scheduler
