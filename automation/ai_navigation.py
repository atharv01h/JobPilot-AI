"""
ai_navigation.py — Autonomous AI Navigation Engine.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from openai import AsyncOpenAI
from playwright.async_api import Page

from config.constants import LLM_BASE_URL, LLM_MODEL
from config.settings import get_settings
from core.logger import get_logger

logger = get_logger(__name__)


class AINavigationEngine:
    """
    Autonomous AI navigation engine that captures page state (DOM, Accessibility Tree,
    OCR text, Screenshot) and queries NVIDIA NIM to decide the next best action.
    """

    def __init__(self, page: Page) -> None:
        self.page = page
        self._client = None
        self._init_llm_client()

    def _init_llm_client(self) -> None:
        settings = get_settings()
        api_key = settings.llm_api_key
        if not api_key:
            logger.warning(
                "AINavigationEngine: LLM_API_KEY is missing. AI navigation will run in fallback mode."
            )
            return
        base_url = settings.llm_base_url or LLM_BASE_URL
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = settings.llm_model or LLM_MODEL

    async def capture_state(self) -> dict:
        """Captures DOM summary, accessibility tree, page text, and base64 screenshot."""
        url = self.page.url
        title = await self.page.title()

        # 1. Get visible interactive elements
        visible_elements = []
        try:
            js_script = """
            () => {
                const elements = [];
                const tags = ['button', 'input', 'select', 'textarea', 'a', '[role="button"]', '[role="checkbox"]', '[role="radio"]'];
                const els = document.querySelectorAll(tags.join(','));
                let index = 0;
                for (const el of els) {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden' || rect.width === 0 || rect.height === 0) {
                        continue;
                    }
                    elements.push({
                        index: index++,
                        tag: el.tagName.toLowerCase(),
                        type: el.type || '',
                        text: (el.innerText || el.value || el.getAttribute('aria-label') || el.placeholder || '').trim().substring(0, 150),
                        placeholder: (el.placeholder || '').substring(0, 100),
                        id: el.id || '',
                        name: el.name || '',
                        role: el.getAttribute('role') || '',
                        aria_haspopup: el.getAttribute('aria-haspopup') || ''
                    });
                }
                return elements;
            }
            """
            visible_elements = await self.page.evaluate(js_script)
        except Exception as e:
            logger.debug(
                "AINavigationEngine: failed to evaluate visible elements: %s", e
            )

        # 2. Get accessibility tree snapshot
        accessibility_tree = "{}"
        try:
            snapshot = await self.page.accessibility.snapshot()
            if snapshot:
                accessibility_tree = json.dumps(snapshot, indent=2)
        except Exception as e:
            logger.debug(
                "AINavigationEngine: failed to get accessibility tree snapshot: %s", e
            )

        # 3. Get page text (OCR text equivalent)
        page_text = ""
        try:
            page_text = await self.page.inner_text("body", timeout=3000)
            page_text = page_text[:2500]  # Cap to avoid token bloat
        except Exception as e:
            logger.debug("AINavigationEngine: failed to get body inner text: %s", e)

        # 4. Screenshot base64 (if vision is enabled)
        screenshot_b64 = None
        try:
            from automation.vision_engine import get_vision_engine

            ve = get_vision_engine()
            if ve._enabled:
                shot_bytes = await self.page.screenshot(type="png", full_page=False)
                if shot_bytes:
                    import base64

                    screenshot_b64 = base64.b64encode(shot_bytes).decode("utf-8")
        except Exception as e:
            logger.debug("AINavigationEngine: failed to capture screenshot: %s", e)

        return {
            "url": url,
            "title": title,
            "visible_elements": visible_elements,
            "accessibility_tree": accessibility_tree,
            "page_text": page_text,
            "screenshot_b64": screenshot_b64,
        }

    async def get_next_action(
        self,
        dom_summary: str,
        visible_elements: list[dict],
        accessibility_tree: str,
        ocr_text: str,
        screenshot_b64: str | None,
        url: str,
        title: str,
        previous_actions: list[str],
        resume_context: str,
        profile_summary: str,
        current_stage: str,
    ) -> dict[str, Any]:
        """Queries the AI model to determine page type, objective, and next structured action."""
        if not self._client:
            logger.warning(
                "AINavigationEngine: No API client. Returning wait action fallback."
            )
            return {
                "action": {"type": "wait", "seconds": 2},
                "reason": "No LLM client configured",
                "confidence": 0.0,
            }

        system_prompt = (
            "You are an autonomous Recruiter AI Navigator. Your job is to navigate a job application "
            "website just like a human recruiter would. You must determine the page type, the user's "
            "objective, and the exact next action to perform. Always reply with valid JSON."
        )

        user_prompt = f"""Analyze the current state of the browser and candidate profile to determine the next action.
        
Current Page Details:
- URL: {url}
- Title: {title}
- Current Stage: {current_stage}

Previous Actions Taken:
{json.dumps(previous_actions, indent=2)}

Candidate Profile Summary:
{profile_summary}

Resume Details:
{resume_context}

DOM Summary & Structure:
{dom_summary}

Visible Clickable / Input Elements:
{json.dumps(visible_elements[:40], indent=2)}

Accessibility Tree Structure:
{accessibility_tree}

OCR Text Detected:
{ocr_text}

Analyze the page. Output a JSON object with the following fields:
1. "page_type": String (e.g. "job_details", "login", "personal_info", "experience", "education", "resume_upload", "custom_questions", "review", "confirmation", "error", "captcha")
2. "objective": String describing what needs to be accomplished on this page.
3. "action": String. Must be one of the following formats:
   - {{"type": "click", "element_index": N, "text": "button text"}}
   - {{"type": "fill", "element_index": N, "value": "text to type"}}
   - {{"type": "upload", "element_index": N}}
   - {{"type": "select", "element_index": N, "option_text": "text"}}
   - {{"type": "check", "element_index": N}}
   - {{"type": "scroll", "direction": "down" | "up"}}
   - {{"type": "wait", "seconds": S}}
   - {{"type": "submit"}}
   - {{"type": "redirect_manual"}}
4. "confidence": Number between 0.0 and 1.0.
5. "reason": String explaining the action.

Respond ONLY with valid JSON.
"""

        messages = [{"role": "system", "content": system_prompt}]

        try:
            from automation.vision_engine import get_vision_engine

            vision = get_vision_engine()
            if vision._enabled and screenshot_b64:
                image_url = f"data:image/png;base64,{screenshot_b64}"
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": image_url}},
                            {"type": "text", "text": user_prompt},
                        ],
                    }
                )
            else:
                messages.append({"role": "user", "content": user_prompt})
        except Exception:
            messages.append({"role": "user", "content": user_prompt})

        try:
            resp = await asyncio.wait_for(
                self._client.chat.completions.create(
                    model=self.model, messages=messages, temperature=0.1, max_tokens=512
                ),
                timeout=25.0,
            )
            text = resp.choices[0].message.content.strip()

            try:
                return json.loads(text)
            except json.JSONDecodeError:
                m = re.search(r"\{.*\}", text, re.DOTALL)
                if m:
                    return json.loads(m.group(0))
                raise ValueError(f"Failed to parse JSON from AI response: {text}")
        except Exception as e:
            logger.error("AINavigationEngine: AI decision failed: %s", e)
            return {
                "action": {"type": "wait", "seconds": 2},
                "reason": f"AI Exception: {e}",
                "confidence": 0.0,
            }
