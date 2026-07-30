"""
browser_health.py — Multi-signal heartbeat watchdog.

Resets the inactivity timer on any DOM changes, network requests,
LLM responses, page navigations, or milestone transitions,
avoiding false-positive browser restarts.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from config.constants import (
    BROWSER_HEALTH_MAX_FAILURES,
    BROWSER_HEALTH_PING_S,
    CDP_PORT,
)
from core.logger import get_logger

logger = get_logger(__name__)

# Progress and milestone timestamps (updated on any activity/milestone progression)
_last_progress_time = time.time()
_last_milestone_time = time.time()
_last_progress_reason = "initialization"

# Execution state dictionary
_execution_state = {
    "milestone": "Unknown",
    "planner_state": "idle",
    "executor_state": "idle",
    "verifier_state": "idle",
    "browser_action": "none",
    "llm_request": "none",
    "playwright_request": "none",
    "recovery_state": "idle",
}


def record_progress(reason: str = "general") -> None:
    """Updates the progress heartbeat timestamp with a reason."""
    global _last_progress_time, _last_progress_reason, _heartbeats
    _last_progress_time = time.time()
    _last_progress_reason = reason
    _heartbeats["browser"] = time.time()
    _heartbeats["planner"] = time.time()
    _heartbeats["executor"] = time.time()
    logger.info("Watchdog: activity recorded. Reason: %s", reason)


def record_milestone_progress() -> None:
    """Updates the milestone progress heartbeat timestamp."""
    global _last_milestone_time, _heartbeats
    _last_milestone_time = time.time()
    _heartbeats["verifier"] = time.time()
    logger.info("Watchdog: milestone progress recorded.")


def update_execution_state(**kwargs) -> None:
    """Updates execution state parameters for the Deadlock Detector."""
    global _execution_state
    _execution_state.update(kwargs)
    record_progress(f"state_updated_{next(iter(kwargs.keys())) if kwargs else 'general'}")


def get_execution_state() -> dict:
    """Returns the current execution state dictionary."""
    return _execution_state


# ── Progress Engine ──────────────────────────────────────────────────────────


class ProgressCounter:
    def __init__(self) -> None:
        self._val = 0

    def increment(self, reason: str = "general") -> None:
        self._val += 1
        record_progress(f"counter_incremented_{reason}")

    @property
    def value(self) -> int:
        return self._val


progress_counter = ProgressCounter()


# ── Heartbeats & Subsystems ──────────────────────────────────────────────────

_heartbeats = {
    "planner": time.time(),
    "executor": time.time(),
    "verifier": time.time(),
    "browser": time.time(),
    "gui": time.time(),
    "database": time.time(),
    "llm": time.time(),
    "recovery": time.time(),
}


def record_heartbeat(subsystem: str) -> None:
    """Records a heartbeat timestamp for a specific subsystem."""
    global _heartbeats
    mapped = subsystem
    if subsystem == "llm_call":
        mapped = "llm"
    elif subsystem == "decision_loop":
        _heartbeats["planner"] = time.time()
        _heartbeats["browser"] = time.time()
        _heartbeats["verifier"] = time.time()
        mapped = "executor"

    if mapped in _heartbeats:
        _heartbeats[mapped] = time.time()


def get_heartbeats() -> dict:
    return _heartbeats


# ── Active Orchestrator & Task Registry ──────────────────────────────────────

_active_orchestrator: Any | None = None
_active_task: asyncio.Task | None = None


def register_active_orchestrator(orchestrator: Any, task: asyncio.Task) -> None:
    global _active_orchestrator, _active_task
    _active_orchestrator = orchestrator
    _active_task = task
    logger.info("Watchdog: registered active orchestrator and task.")


def unregister_active_orchestrator() -> None:
    global _active_orchestrator, _active_task
    _active_orchestrator = None
    _active_task = None
    logger.info("Watchdog: unregistered active orchestrator and task.")


# ── Deadlock Detector ────────────────────────────────────────────────────────


class DeadlockDetector:
    def __init__(self) -> None:
        self.last_progress_counter = -1
        self.last_milestone = ""
        self.last_planner_state = ""
        self.last_executor_state = ""
        self.last_verifier_state = ""
        self.last_browser_action = ""
        self.last_state_change_time = time.time()

    def check_deadlock(
        self, current_counter: int, current_state: dict, timeout_seconds: float = 30.0
    ) -> bool:
        """
        Check if every tracked state remains unchanged beyond the timeout threshold.
        """
        changed = (
            current_counter != self.last_progress_counter
            or current_state.get("milestone") != self.last_milestone
            or current_state.get("planner_state") != self.last_planner_state
            or current_state.get("executor_state") != self.last_executor_state
            or current_state.get("verifier_state") != self.last_verifier_state
            or current_state.get("browser_action") != self.last_browser_action
        )
        if changed:
            self.last_progress_counter = current_counter
            self.last_milestone = current_state.get("milestone", "")
            self.last_planner_state = current_state.get("planner_state", "")
            self.last_executor_state = current_state.get("executor_state", "")
            self.last_verifier_state = current_state.get("verifier_state", "")
            self.last_browser_action = current_state.get("browser_action", "")
            self.last_state_change_time = time.time()
            return False

        elapsed = time.time() - self.last_state_change_time
        if elapsed >= timeout_seconds:
            logger.warning(
                "DeadlockDetector: No state or progress change detected for %.1fs (counter=%d, state=%s). Deadlock declared!",
                elapsed,
                current_counter,
                current_state,
            )
            return True
        return False


# ── Application Health Monitor ───────────────────────────────────────────────


class ApplicationHealthMonitor:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._running = False

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.ensure_future(self._monitor_loop())
        logger.info("ApplicationHealthMonitor started.")

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("ApplicationHealthMonitor stopped.")

    async def _monitor_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(15.0)
                now = time.time()

                # Check if queue is processing
                from services.queue_manager import get_application_queue

                queue_active = get_application_queue()._is_processing

                # 1. Database heartbeat check
                if now - _heartbeats["database"] > 120.0:
                    if queue_active:
                        logger.warning(
                            "ApplicationHealthMonitor: Database heartbeat issue detected but queue is active. Postponing restart..."
                        )
                    else:
                        logger.warning(
                            "ApplicationHealthMonitor: Database heartbeat stopped. Re-initializing..."
                        )
                        try:
                            from core.database import get_database

                            db = get_database()
                            await db.close()
                            await db.initialize()
                            record_heartbeat("database")
                            logger.info(
                                "ApplicationHealthMonitor: Database re-initialized."
                            )
                        except Exception as e:
                            logger.error(
                                "ApplicationHealthMonitor: Database restart failed: %s",
                                e,
                            )

                # 2. Browser heartbeat check
                if now - _heartbeats["browser"] > 120.0:
                    if queue_active:
                        logger.warning(
                            "ApplicationHealthMonitor: Browser heartbeat issue detected but queue is active. Postponing reconnect..."
                        )
                    else:
                        logger.warning(
                            "ApplicationHealthMonitor: Browser heartbeat stopped. Reconnecting pool..."
                        )
                        try:
                            from automation.browser_session_pool import (
                                get_browser_session_pool,
                            )

                            pool = get_browser_session_pool()
                            await pool.reconnect()
                            record_heartbeat("browser")
                            logger.info(
                                "ApplicationHealthMonitor: Browser context reconnected."
                            )
                        except Exception as e:
                            logger.error(
                                "ApplicationHealthMonitor: Browser restart failed: %s",
                                e,
                            )

                # 3. LLM heartbeat check
                if now - _heartbeats["llm"] > 120.0:
                    logger.warning("ApplicationHealthMonitor: LLM heartbeat stopped.")
                    record_heartbeat("llm")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("ApplicationHealthMonitor loop encountered error: %s", e)


class BrowserHealthMonitor:
    """
    Async background task that monitors Brave CDP connectivity and active progress.
    """

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._running = False
        self._consecutive_failures = 0
        self._status = "Not started"
        self._stop_event = asyncio.Event()

    def start(self) -> None:
        """Schedule the monitor loop as an asyncio background Task."""
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._running = True
        self._task = asyncio.ensure_future(self._monitor_loop())
        logger.info(
            "BrowserHealthMonitor started (interval=%ds).", BROWSER_HEALTH_PING_S
        )

    def stop(self) -> None:
        """Signal the monitor to stop gracefully."""
        self._running = False
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("BrowserHealthMonitor stopped.")

    def get_status(self) -> str:
        return self._status

    def get_consecutive_failures(self) -> int:
        return self._consecutive_failures

    # ── Private ──────────────────────────────────────────────────────────────

    async def _monitor_loop(self) -> None:
        try:
            while self._running:
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=BROWSER_HEALTH_PING_S,
                    )
                    break
                except asyncio.TimeoutError:
                    pass

                await self._ping()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("BrowserHealthMonitor loop crashed: %s", exc)

    async def _ping(self) -> None:
        from automation.browser_session_pool import get_browser_session_pool
        from automation.cdp_connector import is_cdp_port_open

        pool = get_browser_session_pool()

        elapsed_activity = time.time() - _last_progress_time
        elapsed_milestone = time.time() - _last_milestone_time

        stall_timeout_activity = BROWSER_HEALTH_PING_S
        stall_timeout_milestone = BROWSER_HEALTH_PING_S * 4

        if (
            elapsed_activity < stall_timeout_activity
            or elapsed_milestone < stall_timeout_milestone
        ):
            logger.debug(
                "BrowserHealthMonitor: Active progress or milestone detected (activity: %.1fs ago [reason: %s], milestone: %.1fs ago) — skipping ping.",
                elapsed_activity,
                _last_progress_reason,
                elapsed_milestone,
            )
            self._status = f"Healthy (activity: {elapsed_activity:.1f}s, milestone: {elapsed_milestone:.1f}s)"
            self._consecutive_failures = 0
            return

        from services.queue_manager import get_application_queue
        queue_active = get_application_queue()._is_processing
        if not queue_active:
            self._status = "Idle (Queue empty)"
            self._consecutive_failures = 0
            return

        try:
            healthy = await asyncio.to_thread(is_cdp_port_open, CDP_PORT)
        except Exception as exc:
            logger.debug("BrowserHealthMonitor ping error: %s", exc)
            healthy = False

        if healthy:
            if self._consecutive_failures > 0:
                logger.info(
                    "BrowserHealthMonitor: browser recovered after %d failure(s).",
                    self._consecutive_failures,
                )
            self._consecutive_failures = 0
            self._status = "Healthy"
        else:
            self._consecutive_failures += 1
            self._status = f"Degraded (failures: {self._consecutive_failures})"
            logger.warning(
                "BrowserHealthMonitor: CDP ping failed — consecutive failures: %d/%d",
                self._consecutive_failures,
                BROWSER_HEALTH_MAX_FAILURES,
            )

            if self._consecutive_failures >= BROWSER_HEALTH_MAX_FAILURES:
                logger.error(
                    "BrowserHealthMonitor: browser declared dead after %d failures — triggering reconnect.",
                    self._consecutive_failures,
                )
                self._status = "Reconnecting..."
                try:
                    success = await pool.reconnect()
                    if success:
                        self._consecutive_failures = 0
                        self._status = "Recovered"
                        logger.info("BrowserHealthMonitor: reconnect successful.")
                    else:
                        self._status = "Recovery failed"
                        logger.error(
                            "BrowserHealthMonitor: reconnect failed — manual restart needed."
                        )
                except Exception as exc:
                    logger.error("BrowserHealthMonitor: reconnect error: %s", exc)
                    self._status = "Recovery error"


# ── Singleton ─────────────────────────────────────────────────────────────────

_monitor: BrowserHealthMonitor | None = None
_health_monitor: ApplicationHealthMonitor | None = None


def get_health_monitor() -> BrowserHealthMonitor:
    global _monitor
    if _monitor is None:
        _monitor = BrowserHealthMonitor()
        try:
            from core.service_registry import ServiceRegistry

            ServiceRegistry.register("Recovery", _monitor)
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)
    return _monitor


def get_app_health_monitor() -> ApplicationHealthMonitor:
    global _health_monitor
    if _health_monitor is None:
        _health_monitor = ApplicationHealthMonitor()
    return _health_monitor
