"""
scraper_context.py — Isolated headless Chromium context for job scrapers.

CRITICAL DESIGN RULE:
  This module creates and owns a DEDICATED headless Chromium context that is
  completely independent of the shared Brave BrowserPool used by the AI agent.

  Scrapers MUST use ScraperContextManager — never pool.get_context().
  The shared Brave pool is exclusive to SmartAIOrchestrator (agent tasks).

  This eliminates all BrowserContext-sharing crashes where one scraper tab
  failure corrupts the entire shared context for every other concurrent task.
"""

from __future__ import annotations

import asyncio

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)
from typing_extensions import Self

from core.logger import get_logger

logger = get_logger(__name__)


class ScraperContextManager:
    """
    Async context manager that creates and owns a dedicated headless
    Chromium BrowserContext for job scraping tasks.

    Usage:
        async with ScraperContextManager() as scraper_ctx:
            page = await scraper_ctx.acquire_page()
            # ... scrape ...
            await scraper_ctx.release_page(page)

    The context is fully closed when the `async with` block exits.
    """

    def __init__(self, timeout_ms: int = 30_000) -> None:
        self._timeout_ms = timeout_ms
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._lock = asyncio.Lock()
        self._page_count = 0

    async def __aenter__(self) -> Self:
        await self._start()
        return self

    async def __aexit__(self, *_) -> None:
        await self._stop()

    # ── Public API ────────────────────────────────────────────────────────────

    async def acquire_page(self) -> Page:
        """Create a new page in the isolated headless context."""
        async with self._lock:
            if self._context is None:
                raise RuntimeError(
                    "ScraperContextManager not started. Use 'async with'."
                )
            page = await self._context.new_page()
            self._page_count += 1
            logger.debug(
                "ScraperContext: page acquired (total open: %d)", self._page_count
            )
            return page

    async def release_page(self, page: Page) -> None:
        """Safely close a scraper page."""
        if page and not page.is_closed():
            try:
                await page.close()
                async with self._lock:
                    self._page_count = max(0, self._page_count - 1)
                logger.debug("ScraperContext: page released.")
            except Exception as exc:
                logger.debug("ScraperContext: page close error (ignored): %s", exc)

    # ── Private ───────────────────────────────────────────────────────────────

    async def _start(self) -> None:
        """Launch a dedicated headless Chromium and create a BrowserContext."""
        logger.info(
            "ScraperContext: launching isolated headless Chromium for scraping…"
        )
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            ignore_https_errors=True,
        )
        self._context.set_default_timeout(self._timeout_ms)
        logger.info("ScraperContext: ready (isolated headless Chromium).")

    async def _stop(self) -> None:
        """Cleanly shut down the headless Chromium context and browser."""
        logger.info("ScraperContext: shutting down isolated scraper context…")
        if self._context:
            try:
                await self._context.close()
            except Exception as exc:
                logger.debug("ScraperContext: context close error (ignored): %s", exc)
            self._context = None

        if self._browser:
            try:
                await self._browser.close()
            except Exception as exc:
                logger.debug("ScraperContext: browser close error (ignored): %s", exc)
            self._browser = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception as exc:
                logger.debug("ScraperContext: playwright stop error (ignored): %s", exc)
            self._playwright = None

        logger.info("ScraperContext: shut down complete.")
