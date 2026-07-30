"""
llm_decision_engine.py — LLM-First Decision Architecture Rebuild (V10).
"""

from __future__ import annotations

import warnings

warnings.filterwarnings("ignore", category=UserWarning, message=".*pin_memory.*")

import asyncio
import base64
import json
import os
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

from playwright.async_api import Locator, Page

from automation.browser_health import record_heartbeat, record_progress
from automation.upload_manager import get_upload_manager
from config.constants import LLM_BASE_URL, LLM_MODEL
from config.settings import get_settings
from core.database import get_database
from core.logger import get_logger
from core.models import Job, JobStatus
from services.resume_intelligence import get_resume_intelligence

logger = get_logger(__name__)


class LLMFirstDecisionEngine:
    """
    Autonomous LLM-First Decision Engine.
    Executes a structured context-driven application loop where the MAIN LLM
    decides every action, reasoning from DOM, Accessibility Tree, and Metadata context.
    OCR and Vision are optional fallbacks only.
    """

    def __init__(self, page: Page) -> None:
        self.page = page
        self._client: Any | None = None
        self._model = LLM_MODEL
        self._init_llm_client()
        self.max_steps = 40
        self.console_messages = []
        try:
            page.on(
                "console",
                lambda msg: self.console_messages.append(f"[{msg.type}] {msg.text}"),
            )
            page.on(
                "pageerror",
                lambda err: self.console_messages.append(f"[ERROR] {err.message}"),
            )
        except Exception as e:
            logger.debug("Failed to bind console event listeners: %s", e)

    def _init_llm_client(self) -> None:
        try:
            settings = get_settings()
            api_key = settings.llm_api_key
            if not api_key:
                logger.warning(
                    "LLMFirstDecisionEngine: LLM_API_KEY not set. AI decisions will fail."
                )
                return

            base_url = settings.llm_base_url or LLM_BASE_URL
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
            self._model = settings.llm_model or LLM_MODEL
            logger.info(
                "LLMFirstDecisionEngine: LLM client initialized successfully using model: %s",
                self._model,
            )
        except Exception as exc:
            logger.error(
                "LLMFirstDecisionEngine: Failed to initialize LLM client: %s", exc
            )

    async def get_website_profile(self, domain: str) -> dict[str, Any]:
        """Loads domain-specific memory, such as successful selectors or login flow details."""
        try:
            db = get_database()
            raw = await db.get_memory(f"profile:website:{domain}")
            if raw:
                return json.loads(raw)
        except Exception as exc:
            logger.debug("Failed to load website profile: %s", exc)
        return {}

    async def save_website_profile(self, domain: str, profile: dict[str, Any]) -> None:
        """Saves domain-specific memory."""
        try:
            db = get_database()
            await db.set_memory(f"profile:website:{domain}", json.dumps(profile))
        except Exception as exc:
            logger.debug("Failed to save website profile: %s", exc)

    async def _capture_state(self, previous_actions: list[str]) -> dict[str, Any]:
        """
        DOM Extractor + Accessibility Tree + Browser Metadata.
        Collects page structure before invoking the reasoning brain.
        """
        url = self.page.url
        title = await self.page.title()

        # 1. DOM Extractor: scan for visible interactive elements
        visible_elements = []
        try:
            js_extractor = """
            () => {
                const elements = [];
                const tags = ['button', 'input', 'select', 'textarea', 'a', '[role="button"]', '[role="checkbox"]', '[role="radio"]', '[role="option"]'];
                const els = document.querySelectorAll(tags.join(','));
                let index = 0;
                
                const getXPath = (element) => {
                    if (element.id) return `//*[@id="${element.id}"]`;
                    const paths = [];
                    for (; element && element.nodeType === Node.ELEMENT_NODE; element = element.parentNode) {
                        let index = 0;
                        for (let sibling = element.previousSibling; sibling; sibling = sibling.previousSibling) {
                            if (sibling.nodeType === Node.DOCUMENT_TYPE_NODE) continue;
                            if (sibling.nodeName === element.nodeName) ++index;
                        }
                        const tagName = element.nodeName.toLowerCase();
                        const pathIndex = index ? `[${index + 1}]` : '';
                        paths.unshift(`${tagName}${pathIndex}`);
                    }
                    return paths.length ? `/${paths.join('/')}` : '';
                };

                for (const el of els) {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    
                    // Simple visibility heuristic
                    if (style.display === 'none' || style.visibility === 'hidden' || rect.width === 0 || rect.height === 0 || style.opacity === '0') {
                        continue;
                    }
                    
                    // Clean text to avoid newlines and spaces
                    const rawText = el.innerText || el.value || el.getAttribute('aria-label') || el.placeholder || '';
                    const cleanText = rawText.trim().replace(/\\s+/g, ' ');
                    
                    elements.push({
                        index: index++,
                        tag: el.tagName.toLowerCase(),
                        type: el.type || '',
                        text: cleanText.substring(0, 150),
                        placeholder: (el.placeholder || '').substring(0, 100),
                        id: el.id || '',
                        name: el.name || '',
                        role: el.getAttribute('role') || el.role || '',
                        required: el.required || el.getAttribute('aria-required') === 'true',
                        checked: el.checked || el.getAttribute('aria-checked') === 'true',
                        aria_describedby: el.getAttribute('aria-describedby') || '',
                        aria_label: el.getAttribute('aria-label') || '',
                        data_testid: el.getAttribute('data-testid') || el.getAttribute('data-test') || el.getAttribute('data-qa') || '',
                        title: el.getAttribute('title') || '',
                        xpath: getXPath(el)
                    });
                }
                return elements;
            }
            """
            visible_elements = await self.page.evaluate(js_extractor)
        except Exception as exc:
            logger.debug("LLMFirstDecisionEngine: DOM extraction failed: %s", exc)

        # 2. Accessibility Tree
        accessibility_tree = {}
        try:
            snapshot = await self.page.accessibility.snapshot()
            if snapshot:
                accessibility_tree = snapshot
        except Exception as exc:
            logger.debug(
                "LLMFirstDecisionEngine: Accessibility snapshot failed: %s", exc
            )

        # 3. Browser Metadata & Dimensions
        browser_state = {
            "url": url,
            "title": title,
            "scroll_x": 0,
            "scroll_y": 0,
            "viewport_width": 1280,
            "viewport_height": 800,
        }
        try:
            dimensions = await self.page.evaluate("""
                () => ({
                    scroll_x: window.scrollX,
                    scroll_y: window.scrollY,
                    viewport_width: window.innerWidth,
                    viewport_height: window.innerHeight
                })
            """)
            browser_state.update(dimensions)
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)

        # 4. Canvas or heavy visual presence detection (to trigger optional OCR/Vision)
        has_canvas_or_heavy_images = False
        try:
            has_canvas_or_heavy_images = await self.page.evaluate("""
                () => {
                    const canvas = document.querySelectorAll('canvas');
                    if (canvas.length > 0) return true;
                    const imgs = document.querySelectorAll('img');
                    for (const img of imgs) {
                        if (img.offsetWidth > 200 && img.offsetHeight > 200) return true;
                    }
                    return false;
                }
            """)
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)

        return {
            "url": url,
            "title": title,
            "visible_elements": visible_elements,
            "accessibility_tree": accessibility_tree,
            "browser_state": browser_state,
            "has_canvas_or_heavy_images": has_canvas_or_heavy_images,
        }

    async def _try_ocr_or_vision(
        self, page_screenshot_bytes: bytes, url: str
    ) -> dict[str, str]:
        """
        Progressive Failover OCR / Vision Perception.
        Attempts Qwen NIM -> Gemini -> OpenAI -> EasyOCR -> PaddleOCR -> DOM fallback.
        """
        from automation.vision_engine import get_vision_engine

        ve = get_vision_engine()

        result = {"ocr": "", "vision": ""}
        if not page_screenshot_bytes:
            return result

        logger.info("LLMFirstDecisionEngine: Invoking optional vision/OCR pipeline...")
        # 1. Try Qwen NIM (through VisionEngine)
        try:
            if ve._enabled:
                resp = await ve._call_vision_api(
                    page_screenshot_bytes,
                    "You are a web observation assistant. Describe what text and buttons are visible in the screenshot.",
                    "Describe the visual layout, text, and active interactive regions in this screenshot.",
                    max_tokens=256,
                    page=self.page,
                )
                if resp:
                    result["vision"] = resp
                    return result
        except Exception as exc:
            logger.debug("Vision NIM failed: %s", exc)

        # 2. Try Gemini Vision
        gemini_key = os.environ.get("GEMINI_API_KEY")
        if gemini_key:
            try:
                b64_img = base64.b64encode(page_screenshot_bytes).decode("utf-8")
                url_api = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key}"
                payload = {
                    "contents": [
                        {
                            "parts": [
                                {
                                    "inlineData": {
                                        "mimeType": "image/png",
                                        "data": b64_img,
                                    }
                                },
                                {
                                    "text": "Analyze this browser screenshot. Extract all visible text, input labels, form fields, and buttons."
                                },
                            ]
                        }
                    ],
                    "generationConfig": {"temperature": 0.1, "maxOutputTokens": 256},
                }
                headers = {"Content-Type": "application/json"}
                req = urllib.request.Request(
                    url_api,
                    data=json.dumps(payload).encode("utf-8"),
                    headers=headers,
                    method="POST",
                )

                def call_gemini():
                    with urllib.request.urlopen(req, timeout=10) as res:
                        return json.loads(res.read().decode("utf-8"))

                resp_data = await asyncio.get_event_loop().run_in_executor(
                    None, call_gemini
                )
                text = resp_data["contents"][0]["parts"][0]["text"]
                if text:
                    result["vision"] = text
                    return result
            except Exception as exc:
                logger.debug("Vision Gemini failed: %s", exc)

        # 3. Try OpenAI Vision
        openai_key = os.environ.get("OPENAI_API_KEY")
        if openai_key:
            try:
                b64_img = base64.b64encode(page_screenshot_bytes).decode("utf-8")
                url_api = "https://api.openai.com/v1/chat/completions"
                payload = {
                    "model": "gpt-4o-mini",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Extract all visible text and input labels from this screenshot.",
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/png;base64,{b64_img}"
                                    },
                                },
                            ],
                        }
                    ],
                    "temperature": 0.1,
                    "max_tokens": 256,
                }
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {openai_key}",
                }
                req = urllib.request.Request(
                    url_api,
                    data=json.dumps(payload).encode("utf-8"),
                    headers=headers,
                    method="POST",
                )

                def call_openai():
                    with urllib.request.urlopen(req, timeout=10) as res:
                        return json.loads(res.read().decode("utf-8"))

                resp_data = await asyncio.get_event_loop().run_in_executor(
                    None, call_openai
                )
                text = resp_data["choices"][0]["message"]["content"]
                if text:
                    result["vision"] = text
                    return result
            except Exception as exc:
                logger.debug("Vision OpenAI failed: %s", exc)

        # 4. Try EasyOCR (Local)
        try:
            import cv2
            import easyocr
            import numpy as np

            reader = easyocr.Reader(["en"], gpu=False)
            nparr = np.frombuffer(page_screenshot_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            results = reader.readtext(img)
            ocr_text = " ".join([text for (_, text, _) in results])
            if ocr_text.strip():
                result["ocr"] = ocr_text
                return result
        except Exception as exc:
            logger.debug("Local EasyOCR failed: %s", exc)

        # 5. Try PaddleOCR (Local)
        try:
            import cv2
            import numpy as np
            from paddleocr import PaddleOCR

            ocr = PaddleOCR(use_angle_cls=True, lang="en")
            nparr = np.frombuffer(page_screenshot_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            ocr_results = ocr.ocr(img, cls=True)
            texts = []
            for line in ocr_results:
                for word in line:
                    texts.append(word[1][0])
            ocr_text = " ".join(texts)
            if ocr_text.strip():
                result["ocr"] = ocr_text
                return result
        except Exception as exc:
            logger.debug("Local PaddleOCR failed: %s", exc)

        # 6. DOM Fallback
        try:
            dom_text = await self.page.evaluate("document.body.innerText")
            result["ocr"] = dom_text[:5000]
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)

        return result

    async def _query_llm(self, context: dict[str, Any]) -> dict[str, Any]:
        """
        Sends the structured Context Builder JSON payload to the MAIN LLM.
        Applies auto-repair for JSON structures and retry mechanisms.
        """
        if not self._client:
            logger.warning(
                "LLMFirstDecisionEngine: No LLM client. Executing safety wait."
            )
            return {
                "action": {"type": "wait", "seconds": 2},
                "reason": "No LLM client configured",
                "confidence": 0.0,
            }

        system_prompt = (
            "You are the Brain of an autonomous job application browser agent. "
            "You must decide the next step to complete the job application on behalf of the applicant.\n"
            "Based on the DOM, Accessibility Tree, Candidate Profile, and History, output a valid JSON decision.\n"
            "Constraints:\n"
            "- Return ONLY valid, parseable JSON.\n"
            "- Do not output markdown, wrappers, or explanations."
        )

        user_prompt = f"""Analyze the browser context and candidate profile to select the best next action.

JSON Context:
{json.dumps(context, indent=2)}

Output schema:
{{
  "goal": "Current step goal (e.g. fill personal info, upload resume, review, complete)",
  "reasoning": "Explain your plan and element choice",
  "confidence": 0.0-1.0,
  "action": {{
    "type": "click" | "fill" | "select" | "check" | "upload" | "scroll" | "wait" | "submit" | "skip",
    "element_index": null or integer index from visible_elements,
    "value": "text to type (if fill)",
    "option_text": "text of option (if select)",
    "direction": "down" or "up" (if scroll),
    "seconds": integer (if wait),
    "reason_code": "optional skip code: INELIGIBLE | ACCOUNT_REQUIRED | CAPTCHA_BLOCKED | UPLOAD_FAILED | APPLICATION_CLOSED | FORM_LOOP | TIMEOUT"
  }},
  "expected_result": "What changes do you expect to see on the page?",
  "validation_rules": {{
    "target_selector_exists": true,
    "expect_page_change": true
  }},
  "recovery_plan": "What to do if expected result is not met"
}}

Answer with valid JSON only:
"""

        for attempt in range(1, 4):
            record_heartbeat("llm_call")
            # Enforce temperature reduction down to 0.0
            temp = max(0.0, 0.1 - (attempt - 1) * 0.05)
            try:
                start_time = time.time()
                resp = await asyncio.wait_for(
                    self._client.chat.completions.create(
                        model=self._model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        temperature=temp,
                        max_tokens=768,
                    ),
                    timeout=30.0,
                )
                raw_text = resp.choices[0].message.content.strip()
                latency = int((time.time() - start_time) * 1000)

                # Log decision to db
                try:
                    db = get_database()
                    await db.log_ai_decision(
                        job_id=None,
                        model_name=self._model,
                        prompt=user_prompt[:2000],
                        response=raw_text,
                        tokens_used=0,
                        latency_ms=latency,
                        decision_type="planning",
                    )
                except Exception as _exc:
                    logger.debug("Suppressed: %s", _exc)

                # Parse JSON
                decision, err_msg = self._parse_json(raw_text)
                if decision and "action" in decision:
                    return decision

                logger.warning(
                    "LLMFirstDecisionEngine: JSON parsing failed or action missing on attempt %d. Error: %s, Raw: %s",
                    attempt,
                    err_msg,
                    raw_text,
                )
                user_prompt += f"\n\nERROR: Your previous output was not valid JSON (Parser error: {err_msg}) or lacked the 'action' field. Try again. You MUST return ONLY valid, parseable JSON matching the exact schema."
            except Exception as exc:
                logger.error(
                    "LLMFirstDecisionEngine: API call failed on attempt %d: %s",
                    attempt,
                    exc,
                )
                await asyncio.sleep(2.0)

        # Fallback to secondary model if main model fails completely
        gemini_key = os.environ.get("GEMINI_API_KEY")
        if gemini_key:
            logger.info(
                "LLMFirstDecisionEngine: Main model failed. Attempting secondary model fallback (Gemini)..."
            )
            try:
                url_api = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key}"
                payload = {
                    "contents": [
                        {"parts": [{"text": f"{system_prompt}\n\n{user_prompt}"}]}
                    ],
                    "generationConfig": {"temperature": 0.0, "maxOutputTokens": 768},
                }
                headers = {"Content-Type": "application/json"}
                req = urllib.request.Request(
                    url_api,
                    data=json.dumps(payload).encode("utf-8"),
                    headers=headers,
                    method="POST",
                )

                def call_gemini():
                    with urllib.request.urlopen(req, timeout=15) as res:
                        return json.loads(res.read().decode("utf-8"))

                resp_data = await asyncio.get_event_loop().run_in_executor(
                    None, call_gemini
                )
                raw_text = resp_data["candidates"][0]["content"]["parts"][0]["text"]
                decision, err_msg = self._parse_json(raw_text)
                if decision and "action" in decision:
                    return decision
            except Exception as exc:
                logger.error("LLMFirstDecisionEngine: Secondary model failed: %s", exc)

        return {
            "action": {"type": "wait", "seconds": 2},
            "reason": "AI Failed completely",
            "confidence": 0.0,
        }

    def _parse_json(self, text: str) -> tuple[dict[str, Any] | None, str | None]:
        """Cleans and extracts JSON code block or JSON brackets from string, returning (data, error_msg)."""
        text = text.strip()
        # Clean markdown code blocks
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()

        try:
            return json.loads(text), None
        except json.JSONDecodeError as e:
            last_err = str(e)

        # Extract content between first { and last }
        start_idx = text.find("{")
        end_idx = text.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            candidate = text[start_idx : end_idx + 1]
            try:
                return json.loads(candidate), None
            except json.JSONDecodeError as e:
                last_err = str(e)
                # Remove trailing commas before a closing brace/bracket
                cleaned = re.sub(r",\s*([\]}])", r"\1", candidate)
                try:
                    return json.loads(cleaned), None
                except json.JSONDecodeError as e2:
                    last_err = str(e2)
        return None, last_err

    async def _locate_element(
        self, el_data: dict[str, Any], selector_fallback: str | None = None
    ) -> Locator | None:
        """Resolves an element locator using stable attributes and falls back to XPath or nth index."""
        tag = el_data.get("tag", "*")
        el_id = el_data.get("id", "")
        el_name = el_data.get("name", "")
        el_text = el_data.get("text", "")
        aria_label = el_data.get("aria_label", "")
        data_testid = el_data.get("data_testid", "")
        title = el_data.get("title", "")
        xpath = el_data.get("xpath", "")
        index = el_data.get("index")

        # 1. Search by data-testid or data-test
        if data_testid:
            loc = self.page.locator(
                f'[data-testid="{data_testid}"], [data-test="{data_testid}"], [data-qa="{data_testid}"]'
            ).first
            try:
                if loc and await loc.count() > 0:
                    return loc
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

        # 2. Search by ID safely (handling special selector chars using [id="..."])
        if el_id:
            loc = self.page.locator(f'[id="{el_id}"]').first
            try:
                if loc and await loc.count() > 0:
                    return loc
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

        # 3. Search by aria-label
        if aria_label:
            loc = self.page.locator(f'[aria-label="{aria_label}"]').first
            try:
                if loc and await loc.count() > 0:
                    return loc
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

        # 4. Search by title
        if title:
            loc = self.page.locator(f'[title="{title}"]').first
            try:
                if loc and await loc.count() > 0:
                    return loc
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

        # 5. Search by name
        if el_name:
            loc = self.page.locator(f'{tag}[name="{el_name}"]').first
            try:
                if loc and await loc.count() > 0:
                    return loc
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

        # 6. Search by clean, single-line text
        if el_text:
            clean_text = re.sub(r"\s+", " ", el_text).strip()
            # Escape quotes
            escaped_text = clean_text.replace("'", "\\'")
            if escaped_text and len(escaped_text) < 100:
                loc = self.page.locator(f"{tag}:has-text('{escaped_text}')").first
                try:
                    if loc and await loc.count() > 0:
                        return loc
                except Exception as _exc:
                    logger.debug("Suppressed: %s", _exc)

        # 7. Search by relative XPath (highly stable fallback)
        if xpath:
            loc = self.page.locator(f"xpath={xpath}").first
            try:
                if loc and await loc.count() > 0:
                    return loc
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

        # 8. Fallback to selector string if provided
        if selector_fallback:
            loc = self.page.locator(selector_fallback).first
            try:
                if loc and await loc.count() > 0:
                    return loc
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

        # 9. Final fallback: index matching
        if index is not None:
            try:
                return self.page.locator(tag).nth(index)
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

        return None

    async def _validate_action(
        self, action: dict[str, Any], state_data: dict[str, Any]
    ) -> tuple[bool, str]:
        """
        Action Validator.
        Checks if the action target element actually exists and is visible before executing.
        """
        action_type = action.get("type")
        if not action_type:
            return False, "Action type is missing"

        if action_type in ("wait", "scroll", "submit", "skip"):
            return True, ""

        element_index = action.get("element_index")
        if element_index is None:
            # Check if selector is provided
            selector = action.get("selector")
            if selector:
                try:
                    loc = self.page.locator(selector).first
                    count = await loc.count()
                    if count > 0 and await loc.is_visible():
                        return True, ""
                    return (
                        False,
                        f"Target selector '{selector}' is not visible or doesn't exist",
                    )
                except Exception as exc:
                    return False, f"Invalid selector '{selector}': {exc}"
            return False, "Target element_index or selector is missing"

        elements = state_data.get("visible_elements", [])
        if element_index < 0 or element_index >= len(elements):
            return (
                False,
                f"Element index {element_index} is out of bounds (0-{len(elements) - 1})",
            )

        el_data = elements[element_index]
        locator = await self._locate_element(el_data)

        if not locator or await locator.count() == 0:
            return False, f"Could not locate element at index {element_index}"

        try:
            if not await locator.is_visible():
                return False, "Element is not visible in DOM"
        except Exception as exc:
            return False, f"Visibility check failed: {exc}"

        return True, ""

    async def _execute_action(
        self, action: dict[str, Any], state_data: dict[str, Any], resume_path: str
    ) -> bool:
        """
        Browser Controller.
        Executes the validated action on the Playwright page.
        """
        action_type = action.get("type")
        if action_type == "wait":
            seconds = int(action.get("seconds", 2))
            logger.info("BrowserController: Waiting %d seconds...", seconds)
            await self.page.wait_for_timeout(seconds * 1000)
            return True

        if action_type == "scroll":
            direction = action.get("direction", "down")
            logger.info("BrowserController: Scrolling %s", direction)
            if direction == "down":
                await self.page.evaluate("window.scrollBy(0, window.innerHeight)")
            else:
                await self.page.evaluate("window.scrollBy(0, -window.innerHeight)")
            return True

        if action_type == "submit":
            logger.info("BrowserController: Clicking Submit button")
            submit_selectors = [
                "button[type='submit']",
                "input[type='submit']",
                "button:has-text('Submit')",
                "button:has-text('Submit Application')",
                "button:has-text('Apply')",
            ]
            for sel in submit_selectors:
                try:
                    loc = self.page.locator(sel).first
                    if await loc.count() > 0 and await loc.is_visible():
                        await loc.click(timeout=3000)
                        return True
                except Exception:
                    continue
            # Generic click submission trigger if selectors fail
            await self.page.keyboard.press("Enter")
            return True

        element_index = action.get("element_index")
        elements = state_data.get("visible_elements", [])

        # Scope selector or locate element
        locator = None
        el_data = {}
        if element_index is not None and 0 <= element_index < len(elements):
            el_data = elements[element_index]
            locator = await self._locate_element(
                el_data, selector_fallback=action.get("selector")
            )
        elif action.get("selector"):
            locator = self.page.locator(action["selector"]).first

        if not locator:
            logger.warning(
                "BrowserController: Target element locator could not be resolved."
            )
            return False

        # Action routing
        try:
            await locator.scroll_into_view_if_needed(timeout=2000)

            if action_type == "click":
                logger.info(
                    "BrowserController: Clicking element %s",
                    el_data.get("text")
                    or action.get("selector")
                    or el_data.get("xpath"),
                )
                await locator.click(timeout=4000)
                return True

            elif action_type == "fill":
                val = action.get("value", "")
                logger.info("BrowserController: Filling input with value: '%s'", val)
                await locator.fill(val, timeout=4000)
                return True

            elif action_type == "upload":
                logger.info("BrowserController: Uploading resume...")
                from automation.upload_manager import get_upload_manager

                um = get_upload_manager()
                domain = urllib.parse.urlparse(self.page.url).netloc
                up_res = await um.upload(
                    self.page, site=domain, container=locator, resume_path=resume_path
                )
                if up_res.success:
                    logger.info("BrowserController: Resume upload success.")
                    return True
                else:
                    logger.warning(
                        "BrowserController: Resume upload failed: %s",
                        up_res.failure_reason,
                    )
                    return False

            elif action_type == "select":
                opt = action.get("option_text", "")
                logger.info("BrowserController: Selecting option: '%s'", opt)
                try:
                    await locator.select_option(label=opt, timeout=4000)
                except Exception:
                    await locator.select_option(value=opt, timeout=4000)
                return True

            elif action_type == "check":
                logger.info("BrowserController: Checking element")
                await locator.check(timeout=4000)
                return True

        except Exception as exc:
            logger.error(
                "BrowserController: Execution error on action '%s': %s",
                action_type,
                exc,
            )
            # Try JS fallback click as a last resort for click actions
            if action_type == "click":
                try:
                    await locator.evaluate("el => el.click()")
                    logger.info("BrowserController: JS fallback click succeeded.")
                    return True
                except Exception as _exc:
                    logger.debug("Suppressed: %s", _exc)
        return False

    async def apply_to_job(
        self, job: Job, resume_path: str, form_data: dict[str, Any]
    ) -> str:
        """
        Executes the autonomous job application loop using a deterministic State Machine.
        Returns the terminal application result status.
        """
        import urllib.parse

        domain = urllib.parse.urlparse(job.url).netloc
        logger.info(
            "LLMFirstDecisionEngine: [START] Processing application for: %s @ %s (%s)",
            job.title,
            job.company,
            job.url,
        )

        # Setup immutable goal context
        original_url = job.url

        current_state = "START"
        final_result = "APPLICATION_FAILED"
        step = 0
        max_steps = 30
        state_retries: dict[str, int] = {}
        max_retries_per_state = 3

        # Load profile memory and resume summaries
        resume_intel = get_resume_intelligence()
        try:
            if not resume_intel.is_ready():
                await resume_intel.initialize()
            if resume_intel.is_ready():
                profile = resume_intel.get_profile()
                if profile:
                    profile.to_context_string()
        except Exception as exc:
            logger.debug("ResumeIntel initialization skipped/failed: %s", exc)

        json.dumps(form_data, indent=2)

        container: Any = None
        # Reset upload manager session

        upload_mgr = get_upload_manager()
        upload_mgr.reset_session()

        while current_state != "DONE" and step < max_steps:
            record_heartbeat("decision_loop")
            step += 1

            # ── 0. ACTIVE TAB DETECTOR ──
            try:
                pages = self.page.context.pages
                if len(pages) > 1:
                    for p in reversed(pages):
                        if p != pages[0] and p.url != "about:blank" and p.url != "":
                            if self.page != p:
                                logger.info(
                                    "LLMFirstDecisionEngine: New active tab detected: %s. Switching controller...",
                                    p.url,
                                )
                                self.page = p
                                try:
                                    await self.page.bring_to_front()
                                except Exception as _exc:
                                    logger.debug("Suppressed: %s", _exc)
                                try:
                                    await self.page.wait_for_load_state(
                                        "domcontentloaded", timeout=5000
                                    )
                                except Exception as _exc:
                                    logger.debug("Suppressed: %s", _exc)
                            break
            except Exception as tab_exc:
                logger.debug("Failed to handle tab switching: %s", tab_exc)

            logger.info(
                "LLMFirstDecisionEngine: Step %d/%d (State: %s, URL: %s)",
                step,
                max_steps,
                current_state,
                self.page.url,
            )

            # Wait for dynamic transitions to settle
            await self.page.wait_for_timeout(500)

            # ── 1. CAPTCHA DETECTOR ──
            try:
                if not self.page.is_closed():
                    from automation.vision_engine import get_vision_engine

                    ve = get_vision_engine()
                    if await ve.detect_captcha(self.page):
                        logger.warning(
                            "LLMFirstDecisionEngine: CAPTCHA detected! Attempting to solve automatically..."
                        )
                        solved = await ve.solve_captcha(self.page)
                        if (
                            solved
                            and not self.page.is_closed()
                            and not await ve.detect_captcha(self.page)
                        ):
                            logger.info(
                                "LLMFirstDecisionEngine: CAPTCHA solved automatically! Resuming..."
                            )
                        else:
                            logger.warning(
                                "LLMFirstDecisionEngine: Auto-solve failed or CAPTCHA still present. Pausing for user input..."
                            )
                            # Wait up to 30 seconds
                            for _ in range(6):
                                if self.page.is_closed():
                                    break
                                await self.page.wait_for_timeout(5000)
                                if self.page.is_closed() or not await ve.detect_captcha(
                                    self.page
                                ):
                                    logger.info(
                                        "LLMFirstDecisionEngine: CAPTCHA cleared! Resuming..."
                                    )
                                    break
            except Exception as e:
                logger.debug("Captcha verification skipped: %s", e)

            # ── 2. NAVIGATION DRIFT DETECTOR ──
            from urllib.parse import urlparse

            original_domain = urlparse(original_url).netloc.lower()
            current_domain = urlparse(self.page.url).netloc.lower()

            drift_url = self.page.url.lower()
            drift_keywords = [
                "jobs-tracker",
                "saved-jobs",
                "search results",
                "home feed",
                "notifications",
                "profile",
                "/feed",
                "/dashboard",
            ]

            # Only trigger drift recovery if we are still on the original portal domain
            if (
                (original_domain == current_domain)
                and any(kw in drift_url for kw in drift_keywords)
                and original_url not in drift_url
            ):
                logger.warning(
                    "LLMFirstDecisionEngine: Navigation drift detected on URL: %s. Initiating recovery...",
                    self.page.url,
                )
                # Close extra tabs
                context_pages = self.page.context.pages
                if len(context_pages) > 1:
                    for p in context_pages[1:]:
                        try:
                            await p.close()
                        except Exception as _exc:
                            logger.debug("Suppressed: %s", _exc)
                    self.page = context_pages[0]
                # Go back
                try:
                    await self.page.go_back(timeout=5000)
                    await self.page.wait_for_timeout(2000)
                except Exception as _exc:
                    logger.debug("Suppressed: %s", _exc)
                # Reopen job URL if still drifted
                if any(kw in self.page.url.lower() for kw in drift_keywords):
                    try:
                        await self.page.goto(
                            original_url, timeout=20000, wait_until="domcontentloaded"
                        )
                    except Exception as e:
                        logger.error(
                            "Navigation drift recovery failed to re-open original URL: %s",
                            e,
                        )
                # Reset state
                current_state = "CLICK_APPLY"
                continue

            # ── 3. STATE RETRY LIMITS ──
            state_retries[current_state] = state_retries.get(current_state, 0) + 1
            if state_retries[current_state] > max_retries_per_state:
                logger.error(
                    "LLMFirstDecisionEngine: State %s failed after %d retries. Aborting job.",
                    current_state,
                    max_retries_per_state,
                )
                final_result = "APPLICATION_FAILED"
                current_state = "SAVE_RESULT"
                continue

            # ── 4. STATE MACHINE TRANSITIONS ──
            if current_state == "START":
                try:
                    await self.page.goto(
                        job.url, timeout=30000, wait_until="domcontentloaded"
                    )
                    record_progress("page_loaded")
                    current_state = "CHECK_ELIGIBILITY"
                except Exception as exc:
                    logger.error("LLMFirstDecisionEngine: Navigation failed: %s", exc)
                    final_result = "APPLICATION_FAILED"
                    current_state = "SAVE_RESULT"

            elif current_state == "CHECK_ELIGIBILITY":
                # Extract and cache the complete job description first
                full_desc = await self._extract_full_job_description()
                if full_desc:
                    job.description = full_desc
                    try:
                        db = get_database()
                        assert job.id is not None
                        await db.update_job_description(job.id, full_desc)
                        logger.info(
                            "LLMFirstDecisionEngine: Extracted and cached full job description (%d chars)",
                            len(full_desc),
                        )
                    except Exception as db_err:
                        logger.debug(
                            "Failed to update job description in DB: %s", db_err
                        )

                # Check for Account/Login wall block conditions
                from automation.account_detector import get_account_detector

                wall = await get_account_detector().detect(self.page)
                if wall:
                    logger.warning(
                        "LLMFirstDecisionEngine: Account/Login wall detected: %s", wall
                    )
                    final_result = wall
                    current_state = "SAVE_RESULT"
                    continue

                # Multi-Signal Smart Apply Decision & Matching Evaluation
                from services.match_evaluator import evaluate_job_match

                match = await evaluate_job_match(job.description)
                score = match.get("score", 0)

                # Fetch min_score setting or default to 75%
                min_score = 75
                try:
                    db = get_database()
                    prefs_raw = await db.get_memory("linkedin_easy_apply_preferences")
                    if prefs_raw:
                        prefs = json.loads(prefs_raw)
                        min_score = int(prefs.get("min_score", "75%").replace("%", ""))
                except Exception as _exc:
                    logger.debug("Suppressed: %s", _exc)

                logger.info(
                    "LLMFirstDecisionEngine: Job match evaluation score: %d%% (Required: %d%%)",
                    score,
                    min_score,
                )
                if score < min_score:
                    logger.warning(
                        "LLMFirstDecisionEngine: Job match score %d%% is below min_score threshold. Skipping.",
                        score,
                    )
                    final_result = "INELIGIBLE"
                    current_state = "SAVE_RESULT"
                    continue

                # Experience level verification
                body_text = ""
                try:
                    body_text = await self.page.inner_text("body", timeout=3000)
                except Exception as _exc:
                    logger.debug("Suppressed: %s", _exc)

                # Check job description for experience suitability
                from config.constants import is_experience_suitable

                if job.experience and not is_experience_suitable(job.experience):
                    logger.warning(
                        "LLMFirstDecisionEngine: Job experience criteria '%s' not suitable.",
                        job.experience,
                    )
                    final_result = "INELIGIBLE"
                    current_state = "SAVE_RESULT"
                    continue

                logger.info(
                    "LLMFirstDecisionEngine: Candidate is eligible. Proceeding to apply."
                )
                current_state = "CLICK_APPLY"

            elif current_state == "CLICK_APPLY":
                # Click apply or Easy Apply
                apply_selectors = [
                    "button:has-text('Easy Apply')",
                    "button:has-text('Apply')",
                    "a:has-text('Apply')",
                    "button.jobs-apply-button",
                    "button#apply-button",
                    ".ia-IndeedApplyButton",
                ]
                clicked = False
                for sel in apply_selectors:
                    try:
                        loc = self.page.locator(sel).first
                        if (
                            await loc.count() > 0
                            and await loc.is_visible()
                            and await loc.is_enabled()
                        ):
                            await loc.click(timeout=5000)
                            clicked = True
                            logger.info(
                                "LLMFirstDecisionEngine: Clicked apply via selector '%s'",
                                sel,
                            )
                            break
                    except Exception:
                        continue

                if not clicked:
                    # Fallback to ClickDecisionEngine
                    try:
                        from automation.click_decision import ClickDecisionEngine

                        btn = await ClickDecisionEngine.rank_and_select(
                            self.page, "APPLY"
                        )
                        if btn:
                            await btn.click(timeout=5000)
                            clicked = True
                    except Exception as _exc:
                        logger.debug("Suppressed: %s", _exc)

                if clicked:
                    current_state = "WAIT_FOR_APPLICATION"
                else:
                    logger.warning("LLMFirstDecisionEngine: Apply button not found.")
                    # If we can't find apply button, check if we are already inside a form page
                    form_present = (
                        await self.page.locator("input, textarea, select").count() > 3
                    )
                    if form_present:
                        current_state = "FILL_FORM"
                    else:
                        final_result = "APPLICATION_FAILED"
                        current_state = "SAVE_RESULT"

            elif current_state == "WAIT_FOR_APPLICATION":
                # Wait for form modal, iframe, or dynamic fields
                try:
                    await self.page.wait_for_selector(
                        "input, select, textarea, iframe[src*='apply'], button:has-text('Next')",
                        timeout=3000,
                    )
                except Exception as _exc:
                    logger.debug("Suppressed: %s", _exc)
                # Scope to iframe if present
                iframe_selector = "iframe[src*='indeedapply'], iframe[title*='Indeed'], iframe[src*='apply']"
                if await self.page.locator(iframe_selector).count() > 0:
                    logger.info(
                        "LLMFirstDecisionEngine: Scoped application inside iframe."
                    )
                current_state = "FILL_FORM"

            elif current_state == "FILL_FORM":
                # Scope target container (iframe or page)
                iframe_selector = "iframe[src*='indeedapply'], iframe[title*='Indeed'], iframe[src*='apply']"
                if await self.page.locator(iframe_selector).count() > 0:
                    container = self.page.frame_locator(iframe_selector)
                else:
                    container = self.page

                # 1. Fill standard fields
                from services.form_intelligence import get_form_intelligence_engine

                get_form_intelligence_engine()

                async def llm_fn(label, field_type, **kwargs):
                    return await self.ask_llm_question(
                        label, field_type, job_desc=job.description or "", **kwargs
                    )

                # Use deterministic module fill fields
                # Instantiate site-specific modules (like LinkedInModule) if available, falling back to BaseWebsiteModule
                from automation.website_modules import (
                    BaseWebsiteModule,
                    get_website_module,
                )

                module_instance = get_website_module(job.source, self.page)
                if not module_instance:
                    module_instance = BaseWebsiteModule(self.page)
                module_instance.job_page = self.page

                try:
                    await module_instance.fill_form_fields_on_container(
                        container, self.page, resume_path, form_data, llm_fn
                    )
                    logger.info(
                        "LLMFirstDecisionEngine: Completed form fields filling."
                    )
                except Exception as e:
                    logger.error("LLMFirstDecisionEngine: Form filling failed: %s", e)
                    final_result = "FORM_FILL_FAILED"
                    current_state = "SAVE_RESULT"
                    continue

                # Check for form validation errors after filling
                try:
                    error_selectors = [
                        "[class*='error']",
                        "[class*='invalid']",
                        "[aria-invalid='true']",
                        ".field-error",
                        ".error-message",
                        "[role='alert']",
                    ]
                    for sel in error_selectors:
                        if await container.locator(sel).count() > 0:
                            logger.warning(
                                "LLMFirstDecisionEngine: Form validation errors detected"
                            )
                            # Try to fix by re-filling or using LLM
                            break
                except Exception as _exc:
                    logger.debug("Suppressed: %s", _exc)

                current_state = "UPLOAD_RESUME"

            elif current_state == "UPLOAD_RESUME":
                iframe_selector = "iframe[src*='indeedapply'], iframe[title*='Indeed'], iframe[src*='apply']"
                if await self.page.locator(iframe_selector).count() > 0:
                    container = self.page.frame_locator(iframe_selector)
                else:
                    container = self.page

                # Resume upload is mandatory checkpoint
                upload_required = await upload_mgr.is_upload_required_on_page(
                    self.page, container
                )
                if upload_required:
                    filename = Path(resume_path).name
                    already_done = await upload_mgr.is_upload_already_verified(
                        self.page, filename
                    )
                    if not already_done:
                        logger.info("LLMFirstDecisionEngine: Uploading resume...")
                        res = await upload_mgr.upload(
                            self.page,
                            site=domain,
                            container=container,
                            resume_path=resume_path,
                        )
                        if not res.success:
                            logger.error(
                                "LLMFirstDecisionEngine: Mandatory resume upload FAILED. Aborting application."
                            )
                            final_result = "UPLOAD_FAILED"
                            current_state = "SAVE_RESULT"
                            continue
                        logger.info("LLMFirstDecisionEngine: Resume upload verified.")
                    else:
                        logger.info("LLMFirstDecisionEngine: Resume already uploaded.")

                current_state = "ANSWER_QUESTIONS"

            elif current_state == "ANSWER_QUESTIONS":
                # Handle any remaining custom questions on the current page
                # Scope target container (iframe or page)
                iframe_selector = "iframe[src*='indeedapply'], iframe[title*='Indeed'], iframe[src*='apply']"
                if await self.page.locator(iframe_selector).count() > 0:
                    container = self.page.frame_locator(iframe_selector)
                else:
                    container = self.page

                # Use form intelligence to detect and answer any unfilled custom questions
                from services.form_intelligence import get_form_intelligence_engine

                get_form_intelligence_engine()

                async def llm_fn(label, field_type, **kwargs):
                    return await self.ask_llm_question(
                        label, field_type, job_desc=job.description or "", **kwargs
                    )

                try:
                    from automation.website_modules import (
                        BaseWebsiteModule,
                        get_website_module,
                    )

                    module_instance = get_website_module(job.source, self.page)
                    if not module_instance:
                        module_instance = BaseWebsiteModule(self.page)
                    module_instance.job_page = self.page

                    # Run a double-check filling sweep using fill_form_fields_on_container
                    await module_instance.fill_form_fields_on_container(
                        container, self.page, resume_path, form_data, llm_fn
                    )
                    logger.info(
                        "LLMFirstDecisionEngine: Completed custom screening question double-check sweep."
                    )
                except Exception as e:
                    logger.debug(
                        "LLMFirstDecisionEngine: Custom question handling error: %s", e
                    )

                current_state = "NEXT_PAGE"

            elif current_state == "NEXT_PAGE":
                # Check for Next / Continue / Review buttons
                iframe_selector = "iframe[src*='indeedapply'], iframe[title*='Indeed'], iframe[src*='apply']"
                if await self.page.locator(iframe_selector).count() > 0:
                    container = self.page.frame_locator(iframe_selector)
                else:
                    container = self.page

                # Check if submit button is visible
                submit_selectors = [
                    "button:has-text('Submit')",
                    "button:has-text('Submit application')",
                    "button:has-text('Apply')",
                    "button:has-text('Complete application')",
                    "button:has-text('Submit Application')",
                    "button:has-text('Finish')",
                    "input[type='submit'][value*='Submit']",
                    "input[type='submit'][value*='Apply']",
                    "input[type='button'][value*='Submit']",
                    "input[type='button'][value*='Apply']",
                    "input[value*='Submit Application']",
                    "input[value*='Submit']",
                    "[id*='submit']",
                    "[class*='submit']",
                    "[name*='submit']",
                    "[role='button']:has-text('Submit')",
                    "[role='button']:has-text('Apply')",
                    "#submit_app",
                    "#post-submit-button",
                    ".template-btn-submit",
                ]
                submit_visible = False
                for sel in submit_selectors:
                    try:
                        loc = container.locator(sel).first
                        if await loc.count() > 0 and await loc.is_visible():
                            submit_visible = True
                            break
                    except Exception:
                        continue

                if submit_visible:
                    current_state = "SUBMIT"
                else:
                    # Click Next/Continue
                    next_selectors = [
                        "button:has-text('Next')",
                        "button:has-text('Continue')",
                        "button:has-text('Save and Continue')",
                        "button:has-text('Next step')",
                        "button:has-text('Save & Continue')",
                        "button:has-text('Review')",
                        "input[type='submit'][value*='Next']",
                        "input[type='submit'][value*='Continue']",
                        "input[type='button'][value*='Next']",
                        "input[type='button'][value*='Continue']",
                        "input[value*='Next']",
                        "input[value*='Continue']",
                        "[id*='next']",
                        "[class*='next']",
                        "[id*='continue']",
                        "[class*='continue']",
                        "[role='button']:has-text('Next')",
                        "[role='button']:has-text('Continue')",
                    ]
                    clicked_next = False
                    for sel in next_selectors:
                        try:
                            loc = container.locator(sel).first
                            if (
                                await loc.count() > 0
                                and await loc.is_visible()
                                and await loc.is_enabled()
                            ):
                                await loc.click(timeout=4000)
                                clicked_next = True
                                logger.info(
                                    "LLMFirstDecisionEngine: Clicked next/continue button using '%s'",
                                    sel,
                                )
                                break
                        except Exception:
                            continue

                    if clicked_next:
                        # Return to FILL_FORM to process the next form page
                        current_state = "FILL_FORM"
                    else:
                        logger.warning(
                            "LLMFirstDecisionEngine: Neither Next nor Submit button found. Trying Submit fallback."
                        )
                        current_state = "SUBMIT"

            elif current_state == "SUBMIT":
                iframe_selector = "iframe[src*='indeedapply'], iframe[title*='Indeed'], iframe[src*='apply']"
                if await self.page.locator(iframe_selector).count() > 0:
                    container = self.page.frame_locator(iframe_selector)
                else:
                    container = self.page

                submit_selectors = [
                    "button:has-text('Submit')",
                    "button:has-text('Submit application')",
                    "button:has-text('Apply')",
                    "button:has-text('Complete application')",
                    "button:has-text('Submit Application')",
                    "button:has-text('Finish')",
                    "input[type='submit'][value*='Submit']",
                    "input[type='submit'][value*='Apply']",
                    "input[type='button'][value*='Submit']",
                    "input[type='button'][value*='Apply']",
                    "input[value*='Submit Application']",
                    "input[value*='Submit']",
                    "[id*='submit']",
                    "[class*='submit']",
                    "[name*='submit']",
                    "[role='button']:has-text('Submit')",
                    "[role='button']:has-text('Apply')",
                    "#submit_app",
                    "#post-submit-button",
                    ".template-btn-submit",
                ]
                clicked_submit = False
                for sel in submit_selectors:
                    try:
                        loc = container.locator(sel).first
                        if (
                            await loc.count() > 0
                            and await loc.is_visible()
                            and await loc.is_enabled()
                        ):
                            await loc.click(timeout=5000)
                            clicked_submit = True
                            logger.info(
                                "LLMFirstDecisionEngine: Clicked Submit button via selector '%s'",
                                sel,
                            )
                            break
                    except Exception:
                        continue

                if not clicked_submit:
                    try:
                        # Press Enter as generic submit trigger
                        await self.page.keyboard.press("Enter")
                        clicked_submit = True
                    except Exception as _exc:
                        logger.debug("Suppressed: %s", _exc)

                try:
                    await self.page.wait_for_load_state("networkidle", timeout=2000)
                except Exception as _exc:
                    logger.debug("Suppressed: %s", _exc)
                current_state = "VERIFY_CONFIRMATION"

            elif current_state == "VERIFY_CONFIRMATION":
                # Multi-signal submission verification: keywords, button status, and modal closure.
                success_keywords = [
                    "application submitted",
                    "thanks for applying",
                    "application received",
                    "confirmation number",
                    "your application has been received",
                    "submitted successfully",
                    "review complete",
                    "thank you",
                    "successfully applied",
                    "apply success",
                ]
                is_success = False
                for _ in range(8):
                    # Check 1: Main page Apply button changes to "Applied"
                    try:
                        apply_btn = self.page.locator(
                            "button.jobs-apply-button, button:has-text('Applied'), [class*='applied']"
                        )
                        if await apply_btn.count() > 0:
                            btn_text = await apply_btn.first.inner_text()
                            if "Applied" in btn_text or "applied" in btn_text.lower():
                                logger.info(
                                    "LLMFirstDecisionEngine: Confirmed via 'Applied' button badge!"
                                )
                                is_success = True
                                break
                    except Exception as _exc:
                        logger.debug("Suppressed: %s", _exc)

                    # Check 2: Modal closed/disappeared
                    try:
                        modal = self.page.locator(
                            "div.jobs-easy-apply-modal, [class*='easy-apply-modal']"
                        )
                        if (
                            await modal.count() == 0
                            or not await modal.first.is_visible()
                        ):
                            logger.info(
                                "LLMFirstDecisionEngine: Confirmed via modal closure!"
                            )
                            is_success = True
                            break
                    except Exception as _exc:
                        logger.debug("Suppressed: %s", _exc)

                    # Check 3: Text content signals
                    body_text = ""
                    title_text = ""
                    try:
                        body_text = await self.page.inner_text("body", timeout=200)
                        title_text = await self.page.title()
                    except Exception as _exc:
                        logger.debug("Suppressed: %s", _exc)
                    content_lower = (
                        body_text + " " + title_text + " " + self.page.url
                    ).lower()
                    if any(kw in content_lower for kw in success_keywords):
                        is_success = True
                        break

                    await asyncio.sleep(0.5)

                if is_success:
                    logger.info("LLMFirstDecisionEngine: Submission confirmed!")
                    final_result = "APPLICATION_SUBMITTED"
                else:
                    # Fallback to Vision check
                    try:
                        ve = get_vision_engine()
                        if ve._enabled and await ve.detect_confirmation(self.page):
                            logger.info(
                                "LLMFirstDecisionEngine: Vision verified submission confirmation."
                            )
                            final_result = "APPLICATION_SUBMITTED"
                        else:
                            logger.warning(
                                "LLMFirstDecisionEngine: Submission confirmation signals not found."
                            )
                            final_result = "APPLICATION_FAILED"
                    except Exception:
                        final_result = "APPLICATION_FAILED"

                current_state = "SAVE_RESULT"

            elif current_state == "SAVE_RESULT":
                assert job.id is not None
                try:
                    db = get_database()
                    if final_result == "APPLICATION_SUBMITTED":
                        await db.mark_applied(
                            job.id, notes="Successfully applied via State Machine"
                        )
                    else:
                        await db.update_job_status(job.id, JobStatus.FAILED)
                        await self._capture_failure_diagnostics(job.id, final_result)
                except Exception as e:
                    logger.error("Failed to save state results to DB: %s", e)
                current_state = "DONE"

        if final_result == "APPLICATION_SUBMITTED":
            return "APPLICATION_SUBMITTED"
        return final_result

    async def _capture_failure_diagnostics(self, job_id: int, reason: str) -> None:
        try:
            import os
            from datetime import datetime, timezone

            os.makedirs("logs/screenshots", exist_ok=True)
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            screenshot_path = f"logs/screenshots/failure_job_{job_id}_{timestamp}.png"
            await self.page.screenshot(path=screenshot_path)
            logger.info("Diagnostic: Failure screenshot saved to %s", screenshot_path)

            log_path = f"logs/screenshots/console_job_{job_id}_{timestamp}.log"
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(
                    f"Reason: {reason}\n\nConsole Log:\n"
                    + "\n".join(self.console_messages)
                )
            logger.info("Diagnostic: Browser console log saved to %s", log_path)
        except Exception as err:
            logger.debug("Failed to capture diagnostics: %s", err)

    async def _extract_full_job_description(self) -> str:
        """Extract the full job description text from the page DOM using common selectors."""
        desc_selectors = [
            ".jobs-description__container",
            ".jobs-description",
            "#job-description",
            "div.jobsearch-JobComponent-description",
            "#jobDescriptionText",
            "div.job-description",
            "div.description",
            "article",
            ".job-details",
        ]
        for sel in desc_selectors:
            try:
                loc = self.page.locator(sel)
                if await loc.count() > 0:
                    text = (await loc.first.inner_text()).strip()
                    if len(text) > 200:
                        return text
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

        # Fallback: return first 5000 chars of body text
        try:
            body_text = await self.page.inner_text("body", timeout=1000)
            return body_text.strip()[:5000]
        except Exception:
            return ""
