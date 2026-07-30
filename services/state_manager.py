"""
state_manager.py — Central Application State Manager (MVC Model/Controller layer).
Acts as the single source of truth for the active browser, queue, AI, and run statuses.
Dispatches state changes to registered GUI listeners on the Tkinter main thread.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from core.logger import get_logger
from core.models import Job

logger = get_logger(__name__)


class AppState(str, Enum):
    IDLE = "IDLE"
    SEARCHING = "SEARCHING"
    QUEUED = "QUEUED"
    APPLYING = "APPLYING"
    PAUSED = "PAUSED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True)
class StateSnapshot:
    app_state: AppState
    is_searching: bool
    current_job: Job | None
    current_ats: str
    current_website: str
    browser_status: str
    current_url: str
    current_tab: str
    cookies_count: int
    screenshot_path: str | None
    live_progress: float
    live_progress_text: str


class StateManager:
    """Central state manager representing application telemetry and statuses."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._dispatcher: Callable[[int, Callable], None] | None = None
        self._listeners: list[Callable[[], None]] = []

        # Application state
        self._app_state: AppState = AppState.IDLE

        # Scraper state
        self._is_searching: bool = False

        # Current application details
        self._current_job: Job | None = None
        self._current_ats: str = "Unavailable"
        self._current_website: str = "Unavailable"

        # Browser metrics
        self._browser_status: str = "Disconnected"
        self._current_url: str = "Unavailable"
        self._current_tab: str = "Unavailable"
        self._cookies_count: int = 0
        self._screenshot_path: str | None = None

        self._live_progress: float = 0.0
        self._live_progress_text: str = ""

    def get_snapshot(self) -> StateSnapshot:
        """Return an immutable, thread-safe snapshot of the current state."""
        with self._lock:
            # We copy the Job Pydantic model safely
            job_copy = self._current_job.copy(deep=True) if self._current_job else None
            return StateSnapshot(
                app_state=self._app_state,
                is_searching=self._is_searching,
                current_job=job_copy,
                current_ats=self._current_ats,
                current_website=self._current_website,
                browser_status=self._browser_status,
                current_url=self._current_url,
                current_tab=self._current_tab,
                cookies_count=self._cookies_count,
                screenshot_path=self._screenshot_path,
                live_progress=self._live_progress,
                live_progress_text=self._live_progress_text,
            )

    def set_dispatcher(self, dispatcher: Callable[[int, Callable], None]) -> None:
        """Set the Tkinter main thread scheduler (e.g. app.after) for safe dispatching."""
        with self._lock:
            self._dispatcher = dispatcher
        logger.debug("StateManager: Dispatcher set successfully")

    def register_listener(self, callback: Callable[[], None]) -> None:
        """Register a callback to run when state changes occur."""
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def unregister_listener(self, callback: Callable[[], None]) -> None:
        """Unregister a previously registered callback."""
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def _notify_listeners(self) -> None:
        """Trigger all registered listeners on the main thread via dispatcher.

        Both the listener list and dispatcher are captured atomically under the lock
        to prevent race conditions during unregistration.
        """
        with self._lock:
            listeners_copy = list(self._listeners)
            disp = self._dispatcher

        for cb in listeners_copy:
            if disp:
                try:
                    disp(0, cb)
                except Exception as exc:
                    logger.error("StateManager: Failed to dispatch callback: %s", exc)
            else:
                # Fallback directly (warn if not on main thread)
                try:
                    cb()
                except Exception as exc:
                    logger.error(
                        "StateManager: Direct callback invocation failed: %s", exc
                    )

    # ── State Updates (Thread-safe setters) ──────────────────────────────────

    def update_state(
        self,
        app_state: AppState | None = None,
        current_job: Job | None = None,
        current_ats: str | None = None,
        current_website: str | None = None,
        browser_status: str | None = None,
        current_url: str | None = None,
        current_tab: str | None = None,
        cookies_count: int | None = None,
        screenshot_path: str | None = None,
        live_progress: float | None = None,
        live_progress_text: str | None = None,
        is_searching: bool | None = None,
    ) -> None:
        """Update any subset of state variables thread-safely and notify GUI."""
        changed = False
        with self._lock:
            if app_state is not None and self._app_state != app_state:
                self._app_state = app_state
                changed = True
            if current_job is not None and self._current_job != current_job:
                self._current_job = current_job
                changed = True
            if current_ats is not None and self._current_ats != current_ats:
                self._current_ats = current_ats
                changed = True
            if current_website is not None and self._current_website != current_website:
                self._current_website = current_website
                changed = True
            if browser_status is not None and self._browser_status != browser_status:
                self._browser_status = browser_status
                changed = True
            if current_url is not None and self._current_url != current_url:
                self._current_url = current_url
                changed = True
            if current_tab is not None and self._current_tab != current_tab:
                self._current_tab = current_tab
                changed = True
            if cookies_count is not None and self._cookies_count != cookies_count:
                self._cookies_count = cookies_count
                changed = True
            if screenshot_path is not None and self._screenshot_path != screenshot_path:
                self._screenshot_path = screenshot_path
                changed = True
            if live_progress is not None and self._live_progress != live_progress:
                self._live_progress = live_progress
                changed = True
            if (
                live_progress_text is not None
                and self._live_progress_text != live_progress_text
            ):
                self._live_progress_text = live_progress_text
                changed = True
            if is_searching is not None and self._is_searching != is_searching:
                self._is_searching = is_searching
                changed = True

        if changed:
            self._notify_listeners()

    # ── Getters ──────────────────────────────────────────────────────────────

    @property
    def app_state(self) -> AppState:
        with self._lock:
            return self._app_state

    @property
    def is_searching(self) -> bool:
        with self._lock:
            return self._is_searching

    @property
    def current_job(self) -> Job | None:
        with self._lock:
            return self._current_job

    @property
    def current_ats(self) -> str:
        with self._lock:
            return self._current_ats

    @property
    def current_website(self) -> str:
        with self._lock:
            return self._current_website

    @property
    def browser_status(self) -> str:
        with self._lock:
            return self._browser_status

    @property
    def current_url(self) -> str:
        with self._lock:
            return self._current_url

    @property
    def current_tab(self) -> str:
        with self._lock:
            return self._current_tab

    @property
    def cookies_count(self) -> int:
        with self._lock:
            return self._cookies_count

    @property
    def screenshot_path(self) -> str | None:
        with self._lock:
            return self._screenshot_path

    @property
    def live_progress(self) -> float:
        with self._lock:
            return self._live_progress

    @property
    def live_progress_text(self) -> str:
        with self._lock:
            return self._live_progress_text


# ── Singleton Getter ──────────────────────────────────────────────────────────

_state_manager: StateManager | None = None


def get_state_manager() -> StateManager:
    global _state_manager
    if _state_manager is None:
        _state_manager = StateManager()
    return _state_manager
