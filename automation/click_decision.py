"""
click_decision.py — Click Decision Engine.
Analyzes and ranks clickable elements by confidence based on semantic similarity/keywords.
"""

from __future__ import annotations

import re

from playwright.async_api import Locator, Page

from core.logger import get_logger

logger = get_logger(__name__)

# Keywords mapping for target actions
KEYWORD_MAPPING: dict[str, list[str]] = {
    "APPLY": [
        "easy apply",
        "apply now",
        "apply",
        "start application",
        "apply on company site",
        "apply on company website",
        "visit employer website",
        "go to company website",
        "apply for this job",
        "start your application",
        "join us",
    ],
    "CONTINUE": [
        "continue",
        "next",
        "continue application",
        "go to next step",
        "proceed",
        "next step",
        "save & continue",
        "save and continue",
        "agree and continue",
        "next page",
    ],
    "SUBMIT": [
        "submit",
        "submit application",
        "finish",
        "done",
        "complete",
        "complete application",
        "send application",
        "file application",
        "finish application",
        "review and submit",
    ],
    "UPLOAD": [
        "upload resume",
        "upload cv",
        "upload",
        "attach",
        "choose file",
        "browse",
        "attach resume",
        "upload document",
        "select files",
    ],
}


class ClickDecisionEngine:
    @staticmethod
    async def rank_and_select(
        page: Page, action_type: str, threshold: float = 0.5
    ) -> Locator | None:
        """
        Scan page for clickable elements, score them against action_type keywords,
        and return the highest confidence element locator if it meets the threshold.
        """
        action_type = action_type.upper()
        keywords = KEYWORD_MAPPING.get(action_type, [])
        if not keywords:
            logger.warning("ClickDecisionEngine: Unknown action_type '%s'", action_type)
            return None

        logger.info(
            "ClickDecisionEngine: Scanning page for '%s' elements...", action_type
        )

        # Select all visible clickable elements
        selectors = [
            "button",
            "a",
            "input[type='button']",
            "input[type='submit']",
            "div[role='button']",
            "[class*='btn']",
            "[class*='button']",
        ]

        candidates: list[tuple[Locator, float, str]] = []

        try:
            # Locate visible elements to avoid unnecessary checks
            all_locators = page.locator(", ".join(selectors))
            count = await all_locators.count()
        except Exception as e:
            logger.error("ClickDecisionEngine: Failed to query elements: %s", e)
            return None

        for i in range(count):
            loc = all_locators.nth(i)
            try:
                # Basic visibility and enabled checks
                if not await loc.is_visible() or not await loc.is_enabled():
                    continue

                # Bounding box sanity check
                box = await loc.bounding_box()
                if not box or box["width"] <= 1 or box["height"] <= 1:
                    continue

                # Extract text representations
                text = (await loc.inner_text()) or ""
                val = (await loc.get_attribute("value")) or ""
                placeholder = (await loc.get_attribute("placeholder")) or ""
                aria_label = (await loc.get_attribute("aria-label")) or ""
                title = (await loc.get_attribute("title")) or ""
                el_class = (await loc.get_attribute("class")) or ""
                el_id = (await loc.get_attribute("id")) or ""

                # Combine all text properties for matching
                search_space = f"{text} {val} {placeholder} {aria_label} {title} {el_class} {el_id}".lower().strip()
                search_space = re.sub(r"\s+", " ", search_space)

                if not search_space:
                    continue

                # Compute score (0.0 to 1.0)
                score = 0.0
                matched_keyword = ""

                for kw in keywords:
                    kw_lower = kw.lower()

                    # 1. Exact text matches (highest weight)
                    text_clean = text.lower().strip()
                    aria_clean = aria_label.lower().strip()
                    val_clean = val.lower().strip()

                    if (
                        text_clean == kw_lower
                        or aria_clean == kw_lower
                        or val_clean == kw_lower
                    ):
                        score = max(score, 1.0)
                        matched_keyword = kw
                    # 2. Starts with / prefix matches
                    elif text_clean.startswith(kw_lower) or aria_clean.startswith(
                        kw_lower
                    ):
                        score = max(score, 0.85)
                        matched_keyword = kw
                    # 3. Substring match
                    elif kw_lower in search_space:
                        score = max(score, 0.7)
                        matched_keyword = kw

                # 4. Contextual boosts
                if score > 0:
                    # Boost primary buttons
                    if (
                        "primary" in el_class.lower()
                        or "submit" in el_class.lower()
                        or "apply" in el_class.lower()
                    ):
                        score = min(score + 0.1, 1.0)

                    # Small boost if element is button tag vs link
                    tag = await loc.evaluate("el => el.tagName.toLowerCase()")
                    if tag == "button" or (tag == "input" and val):
                        score = min(score + 0.05, 1.0)

                    candidates.append((loc, score, matched_keyword))

            except Exception as e:
                logger.debug(
                    "ClickDecisionEngine: Error examining candidate element: %s", e
                )
                continue

        if not candidates:
            logger.info(
                "ClickDecisionEngine: No candidate elements matched for '%s'",
                action_type,
            )
            return None

        # Sort by score descending
        candidates.sort(key=lambda x: x[1], reverse=True)
        best_loc, best_score, best_kw = candidates[0]

        logger.info(
            "ClickDecisionEngine: Selected best candidate with score %.2f (matched keyword: '%s')",
            best_score,
            best_kw,
        )

        if best_score >= threshold:
            return best_loc

        return None
