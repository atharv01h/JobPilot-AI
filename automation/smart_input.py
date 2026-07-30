"""
smart_input.py — Robust input engine with verify-and-fallback logic.

Prevents text corruption, duplication, or blind typing into incorrect elements.
"""

from __future__ import annotations

from playwright.async_api import Locator, Page

from core.logger import get_logger

logger = get_logger(__name__)


async def smart_input(
    context: Page | FrameLocator | Locator,
    selector_or_locator: str | Locator,
    text: str,
    max_retries: int = 3,
) -> bool:
    """
    Inputs text into a field with strict verification using SmartLocatorEngine.
    """
    from playwright.async_api import Page

    from automation.smart_locator import SmartLocatorEngine

    async def _input_action(loc: Locator):
        page = loc.page
        await loc.focus()
        await page.wait_for_timeout(100)

        # Select all and backspace
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Backspace")
        await page.wait_for_timeout(50)

        # Double check clear
        val = await loc.input_value()
        if val:
            await loc.evaluate("el => el.value = ''")

        await loc.fill(text)
        await page.wait_for_timeout(100)

        # Verification & fallback
        val = await loc.input_value()
        if val != text:
            await loc.evaluate(f"""(el) => {{
                el.value = {text!r};
                el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }}""")

    success = await SmartLocatorEngine.execute_action(
        context, selector_or_locator, _input_action, max_attempts=max_retries
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
            await le.record_success(site, "input", selector_str)
        else:
            await le.record_failure(site, "input", "input_failed", selector_str)
    except Exception as learn_err:
        logger.debug("smart_input learning record failed: %s", learn_err)

    return success
