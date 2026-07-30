"""
vision_engine.py — V9 Multimodal Vision AI via NVIDIA NIM (Qwen2.5-VL-72B).

Provides screenshot-based decision making for:
  - Modal state detection (Easy Apply, upload, success, error)
  - Form field context reading (label, placeholder, helper text)
  - Resume upload verification
  - Submission confirmation detection
  - CAPTCHA / challenge detection

Uses the same NVIDIA NIM endpoint and API key as the reasoning model.
No new accounts or keys are needed.
"""

from __future__ import annotations

import warnings

warnings.filterwarnings("ignore", category=UserWarning, message=".*pin_memory.*")

import asyncio
import base64
import json
import re
from typing import Any

from playwright.async_api import Locator, Page

from core.logger import get_logger

logger = get_logger(__name__)


# ── Internal helpers ──────────────────────────────────────────────────────────


def _optimize_image_size(png_bytes: bytes) -> bytes:
    """Resize image to max width 1024px and compress to JPEG format to reduce size for NIM payloads."""
    try:
        import io

        from PIL import Image

        img = Image.open(io.BytesIO(png_bytes))
        # Convert to RGB (required for JPEG conversion)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        max_width = 1024
        if img.width > max_width:
            ratio = max_width / float(img.width)
            new_height = int(float(img.height) * ratio)
            img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)

        out = io.BytesIO()
        img.save(out, format="JPEG", quality=75)
        return out.getvalue()
    except Exception as e:
        logger.debug("Image optimization failed: %s", e)
        return png_bytes


def _encode_page_screenshot(png_bytes: bytes) -> str:
    """Base64-encode a compressed JPEG screenshot for the NVIDIA NIM vision API."""
    optimized = _optimize_image_size(png_bytes)
    return base64.b64encode(optimized).decode("utf-8")


async def _screenshot_page(page: Page) -> bytes | None:
    """Take a page screenshot; returns None on failure."""
    if not page or page.is_closed():
        return None
    try:
        return await page.screenshot(type="png", full_page=False)
    except Exception as exc:
        logger.debug("VisionEngine: screenshot failed: %s", exc)
        return None


async def _screenshot_locator(locator: Locator) -> bytes | None:
    """Screenshot a specific element; returns None on failure."""
    if not locator:
        return None
    try:
        if locator.page.is_closed():
            return None
        return await locator.screenshot(type="png")
    except Exception as exc:
        logger.debug("VisionEngine: element screenshot failed: %s", exc)
        return None


def _parse_json_from_text(text: str) -> Any:
    """Extract and parse the first JSON object or array from LLM text output."""
    # Try direct parse first
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    # Try extracting JSON block
    for pattern in [r"\{.*\}", r"\[.*\]"]:
        m = re.search(pattern, text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return None


# ── Vision Engine ─────────────────────────────────────────────────────────────


class VisionEngine:
    """
    Multimodal AI engine that analyzes browser screenshots using Qwen2.5-VL-72B
    hosted on NVIDIA NIM.

    Every method returns a safe default on failure — vision errors NEVER block
    task execution.
    """

    def __init__(self) -> None:
        from config.constants import LLM_BASE_URL, VISION_MODEL, VISION_TIMEOUT
        from config.settings import get_settings

        settings = get_settings()
        self._api_key = settings.llm_api_key
        self._base_url = LLM_BASE_URL
        self._model = VISION_MODEL
        self._timeout = VISION_TIMEOUT
        self._client = None
        self._enabled = bool(self._api_key)

        if not self._enabled:
            logger.warning(
                "VisionEngine: LLM_API_KEY not set — vision analysis disabled."
            )

    async def validate_endpoint(self) -> bool:
        """
        Validate the vision endpoint by making a minimal check call.
        If unavailable or returns 404/auth errors, disables vision gracefully.
        """
        if not self._enabled:
            logger.info(
                "VisionEngine: Vision analysis is not enabled (key missing). Skipping endpoint validation."
            )
            return False

        dummy_png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
        )
        try:
            logger.info("VisionEngine: Validating vision service endpoint...")
            client = self._get_client()
            b64 = base64.b64encode(dummy_png).decode("utf-8")
            data_url = f"data:image/png;base64,{b64}"
            messages = [
                {"role": "system", "content": "You are a validator."},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {
                            "type": "text",
                            "text": "Is this a 1x1 image? Answer yes or no.",
                        },
                    ],
                },
            ]
            # Use a fast 5.0s timeout for verification
            await asyncio.wait_for(
                client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    max_tokens=10,
                    temperature=0.1,
                ),
                timeout=5.0,
            )
            logger.info("VisionEngine: Vision service validated successfully.")
            return True
        except Exception as exc:
            logger.warning(
                "VisionEngine: Validation failed. Vision service is unavailable (HTTP 404 or other connection error). "
                "Disabling vision gracefully and relying on DOM-based automation. Error: %s",
                exc,
            )
            self._enabled = False
            return False

    def _get_client(self):
        """Lazily initialize the OpenAI-compatible client for NVIDIA NIM."""
        if self._client is None:
            from openai import AsyncOpenAI  # type: ignore

            self._client = AsyncOpenAI(
                base_url=self._base_url,
                api_key=self._api_key,
            )
        return self._client

    async def _call_vision_api(
        self,
        png_bytes: bytes,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 512,
        page: Page | None = None,
    ) -> str | None:
        """
        Send a screenshot + prompt to the active multimodal/OCR vision pipeline.
        Tries providers in sequence: NVIDIA NIM -> Gemini -> OpenAI -> Local OCR -> DOM OCR.
        """
        import base64
        import os
        import time
        import urllib.request

        start_time = time.time()

        # ── 1. NVIDIA NIM (Default) ──────────────────────────────────────────
        if self._enabled and png_bytes:
            try:
                b64 = _encode_page_screenshot(png_bytes)
                data_url = f"data:image/jpeg;base64,{b64}"
                messages = [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": data_url}},
                            {"type": "text", "text": user_prompt},
                        ],
                    },
                ]
                client = self._get_client()
                response = await asyncio.wait_for(
                    client.chat.completions.create(
                        model=self._model,
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=0.1,
                    ),
                    timeout=self._timeout,
                )
                latency = int((time.time() - start_time) * 1000)
                try:
                    from core.database import get_database

                    db = get_database()
                    await db.log_ai_decision(
                        None,
                        self._model,
                        user_prompt,
                        response.choices[0].message.content or "",
                        0,
                        latency,
                        "vision_nvidia",
                    )
                except Exception as _exc:
                    logger.debug("Suppressed: %s", _exc)
                return response.choices[0].message.content
            except Exception as exc:
                logger.warning(
                    "VisionEngine: NVIDIA NIM attempt failed: %s. Trying Gemini...", exc
                )

        # ── 2. Google Gemini Vision ───────────────────────────────────────────
        gemini_key = os.environ.get("GEMINI_API_KEY")
        if gemini_key and png_bytes:
            try:
                b64_img = base64.b64encode(png_bytes).decode("utf-8")
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key}"
                headers = {"Content-Type": "application/json"}
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
                                {"text": f"{system_prompt}\n\n{user_prompt}"},
                            ]
                        }
                    ],
                    "generationConfig": {
                        "temperature": 0.1,
                        "maxOutputTokens": max_tokens,
                    },
                }
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers=headers,
                    method="POST",
                )

                def run_req():
                    with urllib.request.urlopen(req, timeout=12) as res:
                        return json.loads(res.read().decode("utf-8"))

                response_data = await asyncio.get_event_loop().run_in_executor(
                    None, run_req
                )
                text_res = response_data["candidates"][0]["content"]["parts"][0]["text"]
                latency = int((time.time() - start_time) * 1000)
                try:
                    from core.database import get_database

                    db = get_database()
                    await db.log_ai_decision(
                        None,
                        "gemini-1.5-flash",
                        user_prompt,
                        text_res,
                        0,
                        latency,
                        "vision_gemini",
                    )
                except Exception as _exc:
                    logger.debug("Suppressed: %s", _exc)
                return text_res
            except Exception as exc:
                logger.warning(
                    "VisionEngine: Gemini attempt failed: %s. Trying OpenAI...", exc
                )

        # ── 3. OpenAI GPT-4o-mini Vision ──────────────────────────────────────
        openai_key = os.environ.get("OPENAI_API_KEY")
        if openai_key and png_bytes:
            try:
                b64_img = base64.b64encode(png_bytes).decode("utf-8")
                url = "https://api.openai.com/v1/chat/completions"
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {openai_key}",
                }
                payload = {
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": user_prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/png;base64,{b64_img}"
                                    },
                                },
                            ],
                        },
                    ],
                    "temperature": 0.1,
                    "max_tokens": max_tokens,
                }
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers=headers,
                    method="POST",
                )

                def run_openai_req():
                    with urllib.request.urlopen(req, timeout=12) as res:
                        return json.loads(res.read().decode("utf-8"))

                response_data = await asyncio.get_event_loop().run_in_executor(
                    None, run_openai_req
                )
                text_res = response_data["choices"][0]["message"]["content"]
                latency = int((time.time() - start_time) * 1000)
                try:
                    from core.database import get_database

                    db = get_database()
                    await db.log_ai_decision(
                        None,
                        "gpt-4o-mini",
                        user_prompt,
                        text_res,
                        0,
                        latency,
                        "vision_openai",
                    )
                except Exception as _exc:
                    logger.debug("Suppressed: %s", _exc)
                return text_res
            except Exception as exc:
                logger.warning(
                    "VisionEngine: OpenAI attempt failed: %s. Trying Local OCR...", exc
                )

        # ── 4. Local OCR (EasyOCR / PyTesseract / PaddleOCR) + LLM Reasoning ───
        ocr_text = ""
        # A. EasyOCR
        try:
            import cv2
            import easyocr
            import numpy as np

            reader = easyocr.Reader(["en"], gpu=False)
            nparr = np.frombuffer(png_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            results = reader.readtext(img)
            ocr_text = " ".join([text for (_, text, _) in results])
            logger.info("VisionEngine: Extracted text via EasyOCR successfully.")
        except Exception:
            # B. PyTesseract
            try:
                import io

                import pytesseract
                from PIL import Image

                img = Image.open(io.BytesIO(png_bytes))
                ocr_text = pytesseract.image_to_string(img)
                logger.info("VisionEngine: Extracted text via Tesseract successfully.")
            except Exception:
                # C. PaddleOCR
                try:
                    import cv2
                    import numpy as np
                    from paddleocr import PaddleOCR

                    ocr = PaddleOCR(use_angle_cls=True, lang="en")
                    nparr = np.frombuffer(png_bytes, np.uint8)
                    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                    result = ocr.ocr(img, cls=True)
                    texts = []
                    for line in result:
                        for word in line:
                            texts.append(word[1][0])
                    ocr_text = " ".join(texts)
                    logger.info(
                        "VisionEngine: Extracted text via PaddleOCR successfully."
                    )
                except Exception:
                    logger.warning(
                        "VisionEngine: Local OCR methods unavailable or failed."
                    )

        if ocr_text.strip():
            try:
                ans = await self._query_reasoning_model(
                    system_prompt, user_prompt, f"LOCAL_OCR: {ocr_text}"
                )
                if ans:
                    return ans
            except Exception as reason_exc:
                logger.warning(
                    "VisionEngine: LLM reasoning query with OCR failed: %s", reason_exc
                )

        # ── 5. DOM OCR (Playwright innerText) + LLM Reasoning ─────────────────
        if page:
            try:
                logger.info("VisionEngine: Falling back to DOM OCR / page innerText...")
                dom_text = await page.evaluate("document.body.innerText")
                if dom_text and dom_text.strip():
                    ans = await self._query_reasoning_model(
                        system_prompt, user_prompt, f"DOM_TEXT: {dom_text[:20000]}"
                    )
                    if ans:
                        return ans
            except Exception as dom_exc:
                logger.warning("VisionEngine: DOM OCR fallback failed: %s", dom_exc)

        logger.error("VisionEngine: All vision and OCR failover pipelines exhausted.")
        return None

    async def _query_reasoning_model(
        self, system: str, user: str, ocr_context: str
    ) -> str | None:
        """Query standard reasoning LLM as a text-only fallback."""
        from openai import AsyncOpenAI

        from config.constants import LLM_BASE_URL, LLM_MODEL
        from config.settings import get_settings

        settings = get_settings()
        if not settings.llm_api_key:
            return None

        client = AsyncOpenAI(base_url=LLM_BASE_URL, api_key=settings.llm_api_key)
        prompt = (
            f"Here is structured text extracted from the user's browser page context:\n"
            f"-----------------------------------------\n"
            f"{ocr_context}\n"
            f"-----------------------------------------\n\n"
            f"Based on the text above, answer this question: {user}"
        )

        response = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=256,
        )
        return response.choices[0].message.content

    def get_vision_status(self) -> dict:
        """Return the availability status of all vision providers for display in Diagnostics."""
        import importlib
        import os

        from config.settings import get_settings

        settings = get_settings()

        def _check_import(name):
            try:
                importlib.import_module(name)
                return "Available"
            except ImportError:
                return "Not Installed"

        return {
            "NVIDIA NIM Vision": "Available" if settings.llm_api_key else "Missing Key",
            "Gemini Vision API": "Available"
            if os.environ.get("GEMINI_API_KEY")
            else "Missing Key",
            "OpenAI Vision API": "Available"
            if os.environ.get("OPENAI_API_KEY")
            else "Missing Key",
            "EasyOCR (Local)": _check_import("easyocr"),
            "Tesseract (Local)": _check_import("pytesseract"),
            "PaddleOCR (Local)": _check_import("paddleocr"),
            "DOM OCR (Browser)": "Available",
        }

    # ── Public API ────────────────────────────────────────────────────────────

    async def analyze_screenshot(
        self, page: Page, question: str, expected_keys: list[str] | None = None
    ) -> dict[str, Any]:
        """
        Analyze the current page screenshot and answer an arbitrary question.
        Returns a dict with the answer. On failure returns an empty dict.
        """
        png = await _screenshot_page(page)
        if not png:
            return {}

        system = (
            "You are a browser automation AI. Analyze the screenshot of a web page "
            "and answer the question precisely. Always respond with valid JSON."
        )
        user = (
            f"{question}\n\nRespond with valid JSON only. No markdown, no explanation."
        )
        if expected_keys:
            user += f"\nExpected JSON keys: {expected_keys}"

        text = await self._call_vision_api(png, system, user, max_tokens=256, page=page)
        if not text:
            return {}

        result = _parse_json_from_text(text)
        if isinstance(result, dict):
            return result
        return {"answer": text.strip()} if text.strip() else {}

    async def detect_modal_state(self, page: Page) -> str:
        """
        Detect the type of modal/dialog currently open on the page.
        """
        png = await _screenshot_page(page)
        if not png:
            return "unknown"

        system = (
            "You are a browser automation AI specializing in job application websites. "
            "Analyze the screenshot and identify the current UI state."
        )
        user = (
            "What type of modal, dialog, or page state is currently visible? "
            "Choose exactly one from this list: "
            "easy_apply, resume_upload, multi_step_form, success, error, captcha, login, none, unknown. "
            'Respond with JSON: {"state": "<choice>", "confidence": 0.0-1.0, "detail": "<brief description>"}'
        )

        text = await self._call_vision_api(png, system, user, max_tokens=128, page=page)
        if not text:
            return "unknown"

        result = _parse_json_from_text(text)
        if isinstance(result, dict):
            state = result.get("state", "unknown")
            confidence = float(result.get("confidence", 0.0))
            logger.debug(
                "VisionEngine.detect_modal_state: %s (confidence=%.2f, detail=%s)",
                state,
                confidence,
                result.get("detail", ""),
            )
            if confidence >= 0.6:
                return state
        return "unknown"

    async def detect_upload_state(self, page: Page) -> str:
        """
        Detect resume/file upload state.
        """
        png = await _screenshot_page(page)
        if not png:
            return "unknown"

        system = (
            "You are a browser automation AI. "
            "Analyze the screenshot and determine the file upload status."
        )
        user = (
            "What is the current state of the file/resume upload widget? "
            "Choose exactly one: pending, in_progress, complete, error, unknown. "
            'Respond with JSON: {"state": "<choice>", "filename_visible": true/false, "detail": "<brief>"}'
        )

        text = await self._call_vision_api(png, system, user, max_tokens=128, page=page)
        if not text:
            return "unknown"

        result = _parse_json_from_text(text)
        if isinstance(result, dict):
            state = result.get("state", "unknown")
            logger.debug("VisionEngine.detect_upload_state: %s", state)
            return state
        return "unknown"

    async def detect_form_errors(self, page: Page) -> list[dict[str, str]]:
        """
        Detect all visible form validation errors on the current page.
        """
        png = await _screenshot_page(page)
        if not png:
            return []

        system = (
            "You are a browser automation AI. "
            "Analyze the screenshot for form validation errors."
        )
        user = (
            "List all visible form validation error messages on this page. "
            "For each error, identify the field name and error message text. "
            'Respond with JSON array: [{"field": "...", "error": "..."}]. '
            "Return an empty array [] if no errors are visible."
        )

        text = await self._call_vision_api(png, system, user, max_tokens=256, page=page)
        if not text:
            return []

        result = _parse_json_from_text(text)
        if isinstance(result, list):
            return result
        return []

    async def detect_confirmation(self, page: Page) -> bool:
        """
        Return True if the page shows a job application submission confirmation.
        """
        png = await _screenshot_page(page)
        if not png:
            return False

        system = (
            "You are a browser automation AI. "
            "Analyze the screenshot for job application submission confirmation."
        )
        user = (
            "Does this page show a successful job application submission confirmation? "
            "Look for: 'Application submitted', 'Successfully applied', 'Thank you for applying', "
            "confirmation numbers, or any success state. "
            'Respond with JSON: {"confirmed": true/false, "confidence": 0.0-1.0, "evidence": "<text seen>"}'
        )

        text = await self._call_vision_api(png, system, user, max_tokens=128, page=page)
        if not text:
            return False

        result = _parse_json_from_text(text)
        if isinstance(result, dict):
            confirmed = bool(result.get("confirmed", False))
            confidence = float(result.get("confidence", 0.0))
            evidence = result.get("evidence", "")
            logger.info(
                "VisionEngine.detect_confirmation: confirmed=%s (confidence=%.2f, evidence='%s')",
                confirmed,
                confidence,
                evidence,
            )
            return confirmed and confidence >= 0.7
        return False

    async def read_field_context(
        self, page: Page, locator: Locator | None = None
    ) -> dict[str, str]:
        """
        Read the semantic context of a form field.
        """
        png: bytes | None = None
        if locator:
            png = await _screenshot_locator(locator)
        if not png:
            png = await _screenshot_page(page)
        if not png:
            return {}

        system = (
            "You are a browser automation AI. "
            "Analyze the form field element in the screenshot."
        )
        user = (
            "Identify the form field visible in this screenshot. "
            "Extract: label text, placeholder text, helper/instruction text, "
            "and field type (text/email/tel/select/checkbox/radio/textarea/file/date). "
            'Respond with JSON: {"label": "...", "placeholder": "...", '
            '"helper_text": "...", "field_type": "...", "required": true/false}'
        )

        text = await self._call_vision_api(png, system, user, max_tokens=192, page=page)
        if not text:
            return {}

        result = _parse_json_from_text(text)
        if isinstance(result, dict):
            logger.debug("VisionEngine.read_field_context: %s", result)
            return result
        return {}

    async def detect_captcha(self, page: Page) -> bool:
        """Return True if a CAPTCHA or bot challenge is visible on the page."""
        if not page or page.is_closed():
            return False

        # Fast DOM-first signature check
        try:
            captcha_selectors = [
                "iframe[src*='challenges.cloudflare.com']",
                "iframe[src*='recaptcha']",
                "iframe[src*='hcaptcha']",
                "iframe[src*='arkoselabs']",
                ".g-recaptcha",
                ".h-captcha",
                "#cf-challenge-stage",
                "[class*='captcha']",
                "[id*='captcha']",
            ]
            has_captcha_element = False
            for sel in captcha_selectors:
                if await page.locator(sel).count() > 0:
                    loc = page.locator(sel).first
                    if await loc.is_visible():
                        has_captcha_element = True
                        break

            if not has_captcha_element:
                body_text = await page.inner_text("body", timeout=200)
                body_lower = body_text.lower()
                keywords = [
                    "please verify you are human",
                    "complete the security check",
                    "prove you're not a robot",
                    "checking if the site connection is secure",
                    "verify you are a human",
                ]
                if any(kw in body_lower for kw in keywords):
                    has_captcha_element = True

            if not has_captcha_element:
                # No CAPTCHA DOM signatures found - exit fast!
                return False
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)

        png = await _screenshot_page(page)
        if not png:
            return False

        system = "You are a precise CAPTCHA detection AI. Do NOT declare CAPTCHA present unless you see an explicit challenge like reCAPTCHA, hCaptcha, Cloudflare Turnstile, or a distorted text image challenge (CAPTCHA)."
        user = (
            "Is there an active, unsolved CAPTCHA or bot challenge (like hCaptcha, reCAPTCHA, Cloudflare Turnstile checkbox, or distorted alphanumeric text challenge) currently blocking the user on this page? "
            "Ignore simple login forms, cookie banners, or normal inputs. "
            'Respond ONLY with JSON: {"captcha_present": true/false, "type": "recaptcha/hcaptcha/cloudflare/text/none", "details": "reasoning"}'
        )

        text = await self._call_vision_api(png, system, user, max_tokens=96, page=page)
        if not text:
            return False

        result = _parse_json_from_text(text)
        if isinstance(result, dict):
            return bool(result.get("captcha_present", False))
        return False

    async def solve_captcha(self, page: Page) -> bool:
        """Attempts to automatically solve CAPTCHAs on the page using vision."""
        if not page or page.is_closed():
            return False
        logger.info("VisionEngine: Attempting to solve CAPTCHA automatically...")
        try:
            # 1. Check for Cloudflare Turnstile / reCAPTCHA checkbox frames
            checkbox_selectors = [
                "iframe[src*='recaptcha']",
                "iframe[src*='hcaptcha']",
                "iframe[src*='cloudflare']",
                "div.cf-turnstile",
                "[class*='captcha-checkbox']",
                "[id*='captcha-checkbox']",
            ]
            for sel in checkbox_selectors:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    logger.info(
                        "VisionEngine: Found checkbox-based challenge container: %s",
                        sel,
                    )
                    try:
                        box = await loc.bounding_box()
                        if box:
                            cx = box["x"] + box["width"] / 2
                            cy = box["y"] + box["height"] / 2
                            await page.mouse.click(cx, cy)
                            logger.info(
                                "VisionEngine: Clicked checkbox container at coordinates: (%d, %d)",
                                cx,
                                cy,
                            )
                            await page.wait_for_timeout(3000)
                            return True
                    except Exception as e:
                        logger.warning("VisionEngine: Checkbox click failed: %s", e)

            # 2. Check for text CAPTCHA image and input field
            img_selectors = [
                "img[src*='captcha']",
                "img[id*='captcha']",
                "img[class*='captcha']",
                "img[alt*='captcha']",
                "[class*='captcha-image'] img",
            ]
            input_selectors = [
                "input[name*='captcha']",
                "input[id*='captcha']",
                "input[placeholder*='captcha']",
                "input[class*='captcha']",
                "input[title*='captcha']",
            ]

            captcha_img = None
            for sel in img_selectors:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    captcha_img = loc
                    break

            captcha_input = None
            for sel in input_selectors:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    captcha_input = loc
                    break

            if captcha_img and captcha_input:
                logger.info("VisionEngine: Found text CAPTCHA image and input field.")
                img_bytes = await captcha_img.screenshot(type="png")
                if img_bytes:
                    system = "You are a precise text CAPTCHA solver AI."
                    user = "What is the distorted alphanumeric code/text inside this CAPTCHA image? Return ONLY the code/text with no spaces, punctuation, or extra words."
                    solved_text = await self._call_vision_api(
                        img_bytes, system, user, max_tokens=32, page=page
                    )
                    if solved_text:
                        clean_solved = re.sub(r"[^a-zA-Z0-9]", "", solved_text.strip())
                        logger.info(
                            "VisionEngine: Solved CAPTCHA text: '%s'", clean_solved
                        )
                        await captcha_input.fill(clean_solved)
                        await page.wait_for_timeout(1000)
                        await captcha_input.press("Enter")
                        await page.wait_for_timeout(3000)
                        return True
        except Exception as exc:
            logger.error("VisionEngine: Error during auto-solving CAPTCHA: %s", exc)
        return False


# ── Singleton ─────────────────────────────────────────────────────────────────

_vision_engine: VisionEngine | None = None


def get_vision_engine() -> VisionEngine:
    """Return the application-wide singleton VisionEngine."""
    global _vision_engine
    if _vision_engine is None:
        _vision_engine = VisionEngine()
        try:
            from core.service_registry import ServiceRegistry

            ServiceRegistry.register("VisionService", _vision_engine)
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)
    return _vision_engine
