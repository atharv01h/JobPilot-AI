import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from playwright.async_api import FrameLocator, Locator, Page

from automation.smart_click import SmartLocatorResolver
from core.logger import get_logger

logger = get_logger(__name__)


async def ensure_dom_version_tracker(page: Page) -> None:
    """Injects a MutationObserver on the page to track DOM mutations via a window counter."""
    try:
        js_tracker = """
        () => {
            if (window.__dom_version === undefined) {
                window.__dom_version = 0;
                const observer = new MutationObserver(() => {
                    window.__dom_version++;
                });
                observer.observe(document.body, { childList: true, subtree: true, attributes: true });
            }
            return window.__dom_version;
        }
        """
        await page.evaluate(js_tracker)
    except Exception as e:
        logger.debug("SmartLocatorEngine: Failed to inject DOM version tracker: %s", e)


async def get_dom_version(page: Page) -> int:
    """Returns the current DOM version counter from the page."""
    try:
        return await page.evaluate("window.__dom_version || 0")
    except Exception:
        return 0


class SmartLocatorEngine:
    """
    Autonomous Locator and Action Execution Engine.
    Tracks DOM mutations and handles element detachment by automatically re-resolving locators.
    """

    @staticmethod
    async def execute_action(
        context: Page | FrameLocator | Locator,
        selector_or_locator: str | Locator,
        action_fn: Callable[[Locator], Awaitable[Any]],
        max_attempts: int = 3,
    ) -> bool:
        # Resolve page object to inject MutationObserver
        if isinstance(context, Page):
            page = context
        elif hasattr(context, "page"):
            page = context.page
        else:
            # Fallback if no page attribute
            page = None

        if page:
            await ensure_dom_version_tracker(page)
            last_dom_version = await get_dom_version(page)
        else:
            last_dom_version = 0

        for attempt in range(1, max_attempts + 1):
            # Resolve to a unique single locator
            locator = await SmartLocatorResolver.resolve(context, selector_or_locator)
            if not locator:
                logger.debug(
                    "SmartLocatorEngine: Selector/Locator '%s' did not resolve.",
                    selector_or_locator,
                )
                await asyncio.sleep(0.3)
                continue

            try:
                # Basic visibility check before action
                if not await locator.is_visible():
                    logger.debug("SmartLocatorEngine: Element not visible. Waiting...")
                    if page:
                        await page.wait_for_timeout(300)
                    if not await locator.is_visible():
                        continue

                # Run action
                await action_fn(locator)
                return True
            except Exception as e:
                err_str = str(e).lower()

                # Check for stale / detached element
                is_detached = any(
                    kw in err_str
                    for kw in ["detached", "not attached", "stale", "navigated"]
                )

                current_dom_version = await get_dom_version(page) if page else 0
                dom_changed = current_dom_version != last_dom_version

                if (is_detached or dom_changed) and attempt < max_attempts:
                    logger.warning(
                        "SmartLocatorEngine: Detachment or mutation detected (%d -> %d). Re-resolving and retrying... (attempt %d/%d)",
                        last_dom_version,
                        current_dom_version,
                        attempt,
                        max_attempts,
                    )
                    last_dom_version = current_dom_version
                    if page:
                        await page.wait_for_timeout(300)
                    continue
                else:
                    logger.error("SmartLocatorEngine: Action execution failed: %s", e)
                    break
        return False
