from __future__ import annotations

from playwright.async_api import FrameLocator, Locator, Page

from core.logger import get_logger

logger = get_logger(__name__)


class SmartLocatorResolver:
    @staticmethod
    async def resolve(
        context: Page | FrameLocator | Locator,
        selector_or_locator: str | Locator,
    ) -> Locator | None:
        """
        Resolves a selector or locator to exactly one element within the given context.
        If count == 0, returns None.
        If count == 1, returns the single element locator.
        If count > 1, scores candidates and returns the best matching single element locator.
        """
        if isinstance(selector_or_locator, str):
            locator = context.locator(selector_or_locator)
        else:
            locator = selector_or_locator

        try:
            count = await locator.count()
        except Exception as e:
            logger.debug("SmartLocatorResolver: Failed to count matches: %s", e)
            return None

        if count == 0:
            logger.warning(
                "SmartLocatorResolver: No elements matched for selector/locator."
            )
            return None
        if count == 1:
            return locator.first

        logger.info(
            "SmartLocatorResolver: Ambiguous locator matched %d elements. Resolving...",
            count,
        )

        best_score = -1
        best_candidate = None

        for i in range(count):
            candidate = locator.nth(i)
            score = 0

            # Heuristics:
            # 1. Visibility (critical)
            try:
                if await candidate.is_visible():
                    score += 10
            except Exception:
                continue

            # 2. Viewport bounding box check
            try:
                box = await candidate.bounding_box()
                if box and box["width"] > 0 and box["height"] > 0:
                    score += 5
                    if box["width"] >= 12 and box["height"] >= 12:
                        score += 3
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

            # 3. Enabled state
            try:
                if await candidate.is_enabled():
                    score += 5
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

            # 4. Has text content
            try:
                text = await candidate.inner_text()
                if text.strip():
                    score += 2
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

            # 5. Role or ARIA check
            try:
                role = await candidate.get_attribute("role")
                if role in ("button", "link", "checkbox", "radio", "textbox"):
                    score += 3
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

            if score > best_score:
                best_score = score
                best_candidate = candidate

        if best_candidate:
            logger.info(
                "SmartLocatorResolver: Resolved to index with score %d", best_score
            )
            return best_candidate

        return locator.first


async def smart_click(
    context: Page | FrameLocator | Locator,
    selector_or_locator: str | Locator,
    max_retries: int = 3,
) -> bool:
    """
    Clicks an element with verification and fallback, using SmartLocatorEngine to avoid strict mode and stale exceptions.
    Records success or failure to the persistent learning memory.
    """
    from automation.smart_locator import SmartLocatorEngine

    async def _click_action(loc: Locator):
        try:
            await loc.scroll_into_view_if_needed(timeout=2000)
            await loc.click(timeout=3000)
        except Exception as exc:
            logger.warning(
                "smart_click: Standard click failed: %s. Triggering JS fallback click...",
                exc,
            )
            await loc.evaluate("el => el.click()")

    success = await SmartLocatorEngine.execute_action(
        context, selector_or_locator, _click_action, max_attempts=max_retries
    )

    # ── LEARNING INTEGRATION ──────────────────────────────────────────────
    try:
        site = "generic"
        if isinstance(context, Page):
            page = context
        elif hasattr(context, "page"):
            page = context.page
        else:
            page = None
        if page:
            from urllib.parse import urlparse

            domain = urlparse(page.url).netloc.lower()
            if domain:
                site = domain

        selector_str = str(selector_or_locator)
        from services.learning_engine import get_learning_engine

        le = get_learning_engine()
        if success:
            await le.record_success(site, "click", selector_str)
        else:
            await le.record_failure(site, "click", "click_failed", selector_str)
    except Exception as learn_err:
        logger.debug("smart_click learning record failed: %s", learn_err)

    return success
