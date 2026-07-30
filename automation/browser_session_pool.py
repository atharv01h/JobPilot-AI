"""
browser_session_pool.py — Singleton BrowserSession and Playwright Context manager.

CRITICAL DESIGN RULE:
  There must be only ONE Playwright instance, ONE browser (Brave), and
  ONE BrowserContext active at any time. Every module that needs a
  browser session or page MUST get it from this pool — never create its own.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from playwright.async_api import BrowserContext, Page, async_playwright

from config.constants import CDP_PORT
from core.logger import get_logger

logger = get_logger(__name__)


class BrowserSessionPool:
    """
    Manages the lifecycle of the single shared Playwright BrowserContext
    and browser-use BrowserSession.
    """

    def __init__(self) -> None:
        self._session = None  # browser_use BrowserSession
        self._playwright = None  # Playwright async manager
        self._browser = None  # Playwright Browser (CDP only)
        self._context = None  # Playwright BrowserContext
        self._lock = asyncio.Lock()  # serialises all connect/disconnect ops
        self._in_use = False
        self._healthy = False
        self._is_cdp = (
            False  # True if connected to live Brave, False if launched Chromium
        )
        self._task_active = (
            False  # V9: True while agent is actively applying — blocks invalidate/close
        )

    @asynccontextmanager
    async def context(self) -> BrowserContext:
        """
        Context manager for safely acquiring and releasing a BrowserContext.
        Ensures _task_active is properly managed even on exceptions.
        """
        ctx = await self.get_context()
        try:
            yield ctx
        finally:
            await self.release()

    @asynccontextmanager
    async def page(self) -> Page:
        """
        Context manager for safely acquiring and releasing a Page.
        """
        ctx = await self.get_context()
        page = await ctx.new_page()
        try:
            yield page
        finally:
            try:
                await page.close()
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)
            await self.release()

    async def acquire(self) -> object:
        """
        Get the shared browser-use BrowserSession, creating it if necessary.
        Blocks until the session is available (one caller at a time).
        """
        async with self._lock:
            if self._session is None or not self._healthy:
                await self._connect()
            self._in_use = True
            return self._session

    async def release(self) -> None:
        """
        Signal that the current caller is done with the session.
        Does NOT close Brave (keep_alive semantics).
        Also clears the task-active guard.
        """
        async with self._lock:
            self._in_use = False
            self._task_active = False

    async def get_context(self) -> BrowserContext:
        """
        Get the shared Playwright BrowserContext, connecting if necessary.
        Marks the pool as task-active to prevent accidental context destruction.
        """
        async with self._lock:
            if self._context is None or not self._healthy:
                await self._connect()
            self._task_active = True
            return self._context

    async def is_context_alive(self) -> bool:
        """
        Lightweight health check: verify the context is still usable.
        Returns True if the BrowserContext is open and has at least one page slot.
        Never raises — returns False on any error.
        """
        if self._context is None:
            return False
        try:
            _ = self._context.pages  # Raises if context is closed
            return True
        except Exception:
            return False

    async def ensure_page(self, preferred_page: Page | None = None) -> Page:
        """
        Return a healthy Page object.

        If preferred_page is provided and still open, return it as-is.
        Otherwise allocate a new page from the existing context without
        disconnecting or reconnecting the browser.
        """

        # Try to reuse the provided page
        if preferred_page is not None:
            try:
                if not preferred_page.is_closed():
                    return preferred_page
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

        # Allocate a new page
        return await self.get_page()

    async def get_page(self) -> Page:
        """
        Allocate a new Page (tab) in the shared BrowserContext.
        """
        ctx = await self.get_context()
        page = await ctx.new_page()
        logger.debug("Allocated new page in shared context: %s", page)
        return page

    async def invalidate(self) -> None:
        """
        Mark the current session as unhealthy so the next access reconnects.

        V9 GUARD: If a task is actively using the context (_task_active=True),
        this method refuses to close the context and logs a CRITICAL warning.
        Use force_invalidate() only when you are certain no task is running.
        """
        if self._task_active:
            logger.critical(
                "BrowserSessionPool.invalidate() BLOCKED: a task is actively using the context. "
                "Context will NOT be closed. Set _task_active=False via release() first."
            )
            return
        logger.warning(
            "BrowserSessionPool: session invalidated — cleaning up connections."
        )
        await self.close()

    async def force_invalidate(self) -> None:
        """
        Force-invalidate the session regardless of task-active state.
        Use ONLY for unrecoverable failures (e.g., Brave process crash).
        """
        logger.warning(
            "BrowserSessionPool: FORCE invalidate — clearing task-active guard."
        )
        self._task_active = False
        await self.close()

    async def reconnect(self) -> bool:
        """
        Tear down the current session and rebuild it.
        Returns True on success.
        """
        async with self._lock:
            await self._close_internal()
            try:
                await self._connect()
                return True
            except Exception as exc:
                logger.error("BrowserSessionPool reconnect failed: %s", exc)
                return False

    async def health_check(self) -> bool:
        """
        Verify that Brave is still responsive to CDP.
        """
        from automation.cdp_connector import is_cdp_port_open

        healthy = await asyncio.to_thread(is_cdp_port_open, CDP_PORT)
        self._healthy = healthy
        return healthy

    async def close(self) -> None:
        """
        Cleanly shut down the Playwright and browser-use sessions.
        """
        async with self._lock:
            await self._close_internal()

    # ── Private ──────────────────────────────────────────────────────────────

    async def _close_internal(self) -> None:
        """Close connections without holding the lock."""
        self._healthy = False
        if self._session is not None:
            try:
                await self._session.stop()
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)
            self._session = None

        if self._context is not None:
            try:
                await self._context.close()
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)
            self._context = None

        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)
            self._browser = None

        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)
            self._playwright = None

        logger.info("BrowserSessionPool: resources released.")

    async def _connect(self) -> None:
        """
        Build a new BrowserSession and Playwright context connected to Brave.
        MUST be called while holding self._lock.
        """
        from automation.cdp_connector import (
            close_excess_brave_tabs,
            ensure_brave_debug_ready,
            is_cdp_port_open,
        )
        from config.constants import BRAVE_EXE_PATH

        try:
            from browser_use.browser.session import BrowserSession  # type: ignore
        except ImportError:
            raise RuntimeError(
                "browser-use is not installed. Run: pip install browser-use"
            )

        # 1. Start Playwright manager if not running
        if self._playwright is None:
            self._playwright = await async_playwright().start()

        brave_available = Path(BRAVE_EXE_PATH).exists()

        if brave_available:
            brave_ready = await ensure_brave_debug_ready(CDP_PORT)
            if brave_ready and await asyncio.to_thread(is_cdp_port_open, CDP_PORT):
                # Close extra tabs before connecting to avoid deadlocks
                await asyncio.to_thread(close_excess_brave_tabs, CDP_PORT)
                logger.info(
                    "BrowserSessionPool: connecting to Brave via CDP port %d", CDP_PORT
                )

                # Connect Playwright
                self._browser = await self._playwright.chromium.connect_over_cdp(
                    f"http://127.0.0.1:{CDP_PORT}"
                )
                self._context = self._browser.contexts[0]
                self._is_cdp = True

                # Connect browser-use
                self._session = BrowserSession(
                    cdp_url=f"http://127.0.0.1:{CDP_PORT}",
                    keep_alive=True,
                )
                self._healthy = True
                return

        # Fallback: dedicated Chromium profile
        from pathlib import Path as _Path

        _root = _Path(__file__).parent.parent
        profile_dir = str(_root / "browser_profile")
        logger.warning(
            "BrowserSessionPool: Brave unavailable — launching Chromium profile at %s",
            profile_dir,
        )

        # Launch Chromium with debugging port open so browser-use can connect via CDP
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=False,
            ignore_default_args=["--enable-automation"],
            args=[
                f"--remote-debugging-port={CDP_PORT}",
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--start-maximized",
            ],
        )
        self._browser = None  # Persistent contexts own their browser process
        self._is_cdp = False

        # Connect browser-use to the launched Chromium debugging port
        self._session = BrowserSession(
            cdp_url=f"http://127.0.0.1:{CDP_PORT}",
            keep_alive=True,
        )
        self._healthy = True

    @property
    def is_in_use(self) -> bool:
        return self._in_use

    @property
    def is_healthy(self) -> bool:
        return self._healthy


# ── Singleton ─────────────────────────────────────────────────────────────────

_pool: BrowserSessionPool | None = None


def get_browser_session_pool() -> BrowserSessionPool:
    """Return the application-wide singleton BrowserSessionPool."""
    global _pool
    if _pool is None:
        _pool = BrowserSessionPool()
    return _pool
