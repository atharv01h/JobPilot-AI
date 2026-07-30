"""
upload_manager.py — Professional Resume Upload System (V10).

DESIGN PHILOSOPHY:
  Upload is a MANDATORY CHECKPOINT.
  If upload is required on a page and ALL strategies fail:
    - Return UPLOAD_FAILED immediately.
    - Caller MUST NOT press Next/Continue/Save/Submit after this.
    - Caller closes tab and moves to next job.

  Upload strategy waterfall (highest-priority first):
    1. Shadow DOM     — JS deep traversal of all shadow roots
    2. Iframe Search  — recursively scan every iframe for file inputs
    3. React Hidden   — dispatch synthetic events to React-bound hidden inputs
    4. Drag Drop      — DataTransfer simulation for Dropzone/FilePond/Uppy zones
    5. Aria Button    — click ARIA/SVG upload buttons → intercept FileChooser
    6. Direct         — input[type="file"] set_input_files() (visible or hidden)
    7. FileChooser    — click upload button → intercept FileChooser event
    8. Reveal         — JS-reveal hidden file input → set_input_files()
    9. WinUI          — pywinauto: detect Windows Open File dialog

  Upload deduplication:
    Once upload is verified successful, NEVER upload again for this application
    UNLESS a "Replace / Update / Upload CV" button appears.

  Upload verification (any ONE signal = success):
    - Filename/stem visible in page body text
    - Progress bar at 100% / complete state
    - Resume preview element visible
    - Delete/Replace/Remove button appeared
    - input[type=file].files.length > 0 (JS check)
    - Site-specific verify selectors

  Compatible with: Workday, Greenhouse, Lever, Oracle, SuccessFactors, iCIMS,
                   Taleo, SmartRecruiters, Ashby, Jobvite, LinkedIn, Indeed,
                   Naukri, Foundit, Wellfound, Instahyre, Glassdoor,
                   Dropzone.js, FilePond, Uppy, Material UI, Bootstrap modals.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from playwright.async_api import FileChooser, Locator, Page

from core.logger import get_logger

logger = get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_MAX_UPLOAD_SIZE_MB = 10
_VERIFY_TIMEOUT_S = 15.0
_CHOOSER_TIMEOUT_MS = 8_000
_REVEAL_RESTORE_DELAY = 0.3

# Upload button trigger selectors (ordered by specificity)
_UPLOAD_TRIGGER_SELECTORS = [
    "button:has-text('Upload resume')",
    "button:has-text('Upload CV')",
    "button:has-text('Upload')",
    "button:has-text('Attach')",
    "button:has-text('Choose file')",
    "button:has-text('Browse')",
    "button:has-text('Add resume')",
    "button:has-text('Attach resume')",
    "a:has-text('Upload resume')",
    "a:has-text('Upload CV')",
    "a:has-text('Upload')",
    "label[for]",
    "[class*='upload'][class*='btn']",
    "[class*='upload-button']",
    "[class*='resume-upload']",
    "[class*='attach']",
    "[aria-label*='upload' i]",
    "[aria-label*='attach' i]",
    "[data-test*='upload']",
    "[data-testid*='upload']",
    # Drag-and-drop zones
    "[class*='dropzone']",
    "[class*='drop-zone']",
    "[class*='file-drop']",
    "[class*='filepond']",
    "[class*='uppy']",
    "div[role='button'][aria-label*='upload' i]",
]

# File input selectors
_FILE_INPUT_SELECTORS = [
    "input[type='file']",
    "input[type='file'][accept*='pdf']",
    "input[type='file'][accept*='.pdf']",
    "input[type='file'][accept*='doc']",
    "input[type='file'][accept*='.doc']",
]

# Verification: presence of any of these = upload confirmed
_UPLOAD_SUCCESS_KEYWORDS = [
    ".pdf",
    ".doc",
    ".docx",
    "uploaded",
    "resume uploaded",
    "cv uploaded",
    "file uploaded",
    "upload complete",
    "upload successful",
    "file attached",
    "attached",
    "upload successful",
    "successfully uploaded",
    "document uploaded",
    "file received",
]

# Replace/Update button texts — triggers re-upload eligibility
_REPLACE_KEYWORDS = [
    "replace resume",
    "replace cv",
    "update resume",
    "upload updated resume",
    "upload new resume",
    "change resume",
    "remove and re-upload",
    "upload cv",
    "upload a different file",
]

# Error strings confirming upload failure
_UPLOAD_ERROR_KEYWORDS = [
    "upload failed",
    "file too large",
    "invalid file",
    "unsupported format",
    "upload error",
    "error uploading",
    "file not accepted",
    "try again",
]


# ── Data Types ────────────────────────────────────────────────────────────────


class UploadStrategy(Enum):
    SHADOW_DOM = auto()  # JS deep shadow root traversal
    IFRAME_SEARCH = auto()  # Scan all iframes recursively
    REACT_HIDDEN = auto()  # React synthetic event dispatch
    DRAG_DROP = auto()  # DataTransfer simulation (Dropzone/FilePond/Uppy)
    ARIA_BUTTON = auto()  # ARIA/SVG upload button → FileChooser
    DIRECT = auto()  # set_input_files() on visible/hidden input
    FILE_CHOOSER = auto()  # expect_file_chooser() + trigger button
    REVEAL = auto()  # JS reveal hidden input → set_input_files()
    WINDOWS_UI = auto()  # pywinauto fallback for native OS dialog


@dataclass
class UploadResult:
    success: bool = False
    strategy_used: UploadStrategy | None = None
    duration_s: float = 0.0
    retry_count: int = 0
    filename: str = ""
    failure_reason: str = ""
    verified: bool = False

    def __str__(self) -> str:
        strat = self.strategy_used.name if self.strategy_used else "NONE"
        return (
            f"UploadResult(success={self.success}, strategy={strat}, "
            f"verified={self.verified}, duration={self.duration_s:.2f}s, "
            f"retries={self.retry_count}, reason='{self.failure_reason}')"
        )


# ── Resume Manager ────────────────────────────────────────────────────────────


class ResumeManager:
    """
    Validates and manages the resume file.
    Caches the resolved absolute path.
    Supports per-site resume overrides.
    """

    ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx"}

    def __init__(self) -> None:
        self._default_path: Path | None = None
        self._site_overrides: dict[str, Path] = {}
        self._cache: dict[str, dict] = {}

    def set_default(self, path: str) -> bool:
        return self._validate_and_store(path, site=None)

    def set_site_override(self, site: str, path: str) -> bool:
        return self._validate_and_store(path, site=site.lower())

    def get_path(self, site: str = "") -> str | None:
        p: Path | None = self._site_overrides.get(site.lower())
        if p is None:
            p = self._default_path
        if p is None:
            self._load_from_settings()
            p = self._default_path
        return str(p) if p and p.exists() else None

    def get_metadata(self, path: str) -> dict:
        return self._cache.get(path, {})

    def validate(self, path: str) -> tuple[bool, str]:
        p = Path(path)
        if not p.exists():
            return False, f"File not found: {path}"
        if not p.is_file():
            return False, f"Not a file: {path}"
        if p.suffix.lower() not in self.ALLOWED_EXTENSIONS:
            return False, f"Unsupported extension '{p.suffix}'. Use PDF, DOC, or DOCX."
        size_mb = p.stat().st_size / (1024 * 1024)
        if size_mb > _MAX_UPLOAD_SIZE_MB:
            return (
                False,
                f"File too large: {size_mb:.1f} MB (limit {_MAX_UPLOAD_SIZE_MB} MB)",
            )
        try:
            with open(p, "rb") as f:
                f.read(4)
        except PermissionError:
            return False, f"File not readable (permission denied): {path}"
        return True, ""

    def _validate_and_store(self, path: str, site: str | None) -> bool:
        valid, err = self.validate(path)
        if not valid:
            logger.error("ResumeManager: validation failed for '%s': %s", path, err)
            return False
        p = Path(path).resolve()
        meta = {
            "abs_path": str(p),
            "filename": p.name,
            "size_kb": round(p.stat().st_size / 1024, 1),
        }
        self._cache[str(p)] = meta
        if site is None:
            self._default_path = p
            logger.info(
                "ResumeManager: default resume set → %s (%.1f KB)",
                p.name,
                meta["size_kb"],
            )
        else:
            self._site_overrides[site] = p
            logger.info("ResumeManager: site override for '%s' → %s", site, p.name)
        return True

    def _load_from_settings(self) -> None:
        try:
            from config.settings import get_settings

            settings = get_settings()
            if settings.resume_path:
                self._validate_and_store(settings.resume_path, site=None)
        except Exception as exc:
            logger.debug("ResumeManager: could not load from settings: %s", exc)


# ── Upload Manager ────────────────────────────────────────────────────────────


class UploadManager:
    """
    V10 — Mandatory-checkpoint resume upload engine.

    After ALL strategies fail, returns success=False.
    The caller is REQUIRED to stop the application — never continue after failure.

    Tracks whether upload was already completed to avoid duplicate uploads.
    Only re-uploads if a Replace/Update button appears on the page.
    """

    def __init__(self, resume_manager: ResumeManager | None = None) -> None:
        self._rm = resume_manager or get_resume_manager()
        self._site_strategy_cache: dict[str, UploadStrategy] = {}
        # Per-application upload state — reset by calling reset_session()
        self._upload_verified: bool = False

    def reset_session(self) -> None:
        """Call at the start of each new job application to reset upload state."""
        self._upload_verified = False

    # ── Main Entry Point ──────────────────────────────────────────────────────

    async def upload(
        self,
        page: Page,
        site: str = "",
        container=None,
        resume_path: str | None = None,
    ) -> UploadResult:
        """
        Upload the resume using the best available strategy.

        MANDATORY CHECKPOINT: caller MUST check result.success.
        If False, the application MUST be aborted — never continue pressing buttons.

        Returns UploadResult with full audit details.
        """
        start = time.monotonic()

        # ── Already uploaded this session? ─────────────────────────────────
        if self._upload_verified:
            # Check if a Replace/Update button appeared
            replace_visible = await self._check_replace_button(page)
            if not replace_visible:
                logger.info(
                    "UploadManager: resume already uploaded this session — skipping re-upload."
                )
                return UploadResult(
                    success=True,
                    failure_reason="already_uploaded_skip",
                    duration_s=time.monotonic() - start,
                    verified=True,
                )
            else:
                logger.info(
                    "UploadManager: Replace/Update button detected — allowing re-upload."
                )
                self._upload_verified = False

        # ── Resolve resume path ────────────────────────────────────────────
        path = resume_path or self._rm.get_path(site)
        if not path:
            return UploadResult(
                success=False,
                failure_reason="No valid resume path configured",
                duration_s=time.monotonic() - start,
            )

        valid, err = self._rm.validate(path)
        if not valid:
            return UploadResult(
                success=False,
                failure_reason=err,
                duration_s=time.monotonic() - start,
            )

        filename = Path(path).name
        size_kb = Path(path).stat().st_size / 1024
        logger.info(
            "UploadManager: starting upload [site=%s, file=%s, size=%.1f KB]",
            site or "unknown",
            filename,
            size_kb,
        )

        # ── Load site profile ─────────────────────────────────────────────
        from automation.site_upload_profiles import get_profile

        profile = get_profile(site)
        if profile:
            logger.debug(
                "UploadManager: site profile loaded for '%s' (preferred=%s)",
                site,
                profile.preferred_strategy,
            )
            if container is None and profile.iframe_selectors:
                for iframe_sel in profile.iframe_selectors:
                    try:
                        if await page.locator(iframe_sel).count() > 0:
                            container = page.frame_locator(iframe_sel)
                            logger.info(
                                "UploadManager: auto-scoped to iframe '%s' for site '%s'",
                                iframe_sel,
                                site,
                            )
                            break
                    except Exception as _exc:
                        logger.debug("Suppressed: %s", _exc)

        # ── Strategy waterfall ────────────────────────────────────────────
        db_preferred = None
        try:
            from services.learning_engine import get_learning_engine

            db_pref_name = await get_learning_engine().get_best_selector(
                site.lower() or "generic", "upload_strategy"
            )
            if db_pref_name:
                from automation.upload_manager import UploadStrategy

                db_preferred = UploadStrategy[db_pref_name]
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)

        strategies = self._get_strategy_order(site, profile, db_preferred)
        retry_count = 0
        last_reason = ""

        for strategy in strategies:
            retry_count += 1
            logger.info(
                "UploadManager: trying strategy %s (attempt %d/%d)",
                strategy.name,
                retry_count,
                len(strategies),
            )

            try:
                result = await self._execute_strategy(
                    strategy, page, container, path, filename, profile
                )
            except Exception as exc:
                result = UploadResult(
                    success=False,
                    strategy_used=strategy,
                    failure_reason=str(exc),
                )

            result.duration_s = time.monotonic() - start
            result.retry_count = retry_count
            result.filename = filename

            if result.success:
                result.verified = await self._verify_upload(page, filename, profile)
                if result.verified:
                    self._upload_verified = True
                    self._site_strategy_cache[site.lower()] = strategy
                    logger.info(
                        "UploadManager: ✅ SUCCESS via %s in %.2fs. %s",
                        strategy.name,
                        result.duration_s,
                        result,
                    )
                    # Record success in learning engine
                    try:
                        from services.learning_engine import get_learning_engine

                        await get_learning_engine().record_success(
                            site=site.lower() or "generic",
                            selector_type="upload_strategy",
                            selector_value=strategy.name,
                        )
                    except Exception as _exc:
                        logger.debug("Suppressed: %s", _exc)
                    return result
                else:
                    logger.warning(
                        "UploadManager: strategy %s uploaded but verification FAILED — trying next.",
                        strategy.name,
                    )
                    result.success = False
                    result.failure_reason = "Verification failed after upload"
                    # Record failure in learning engine
                    try:
                        from services.learning_engine import get_learning_engine

                        await get_learning_engine().record_failure(
                            site=site.lower() or "generic",
                            context=f"upload_strategy:{strategy.name}",
                            reason=result.failure_reason or "verification_failed",
                        )
                    except Exception as _exc:
                        logger.debug("Suppressed: %s", _exc)
            else:
                logger.warning(
                    "UploadManager: strategy %s FAILED: %s",
                    strategy.name,
                    result.failure_reason,
                )
                last_reason = result.failure_reason
                # Record failure in learning engine
                try:
                    from services.learning_engine import get_learning_engine

                    await get_learning_engine().record_failure(
                        site=site.lower() or "generic",
                        context=f"upload_strategy:{strategy.name}",
                        reason=result.failure_reason or "strategy_failed",
                    )
                except Exception as _exc:
                    logger.debug("Suppressed: %s", _exc)

        # ── All strategies exhausted ──────────────────────────────────────
        final = UploadResult(
            success=False,
            strategy_used=strategies[-1] if strategies else None,
            duration_s=time.monotonic() - start,
            retry_count=retry_count,
            filename=filename,
            failure_reason=f"UPLOAD_FAILED — all {len(strategies)} strategies exhausted. Last: {last_reason}",
        )
        logger.error("UploadManager: ❌ ALL strategies exhausted. %s", final)
        return final

    # ── Deduplication helper ──────────────────────────────────────────────────

    async def _check_replace_button(self, page: Page) -> bool:
        """Return True if a Replace/Update resume button is visible on the page."""
        try:
            body = await page.inner_text("body", timeout=3000)
            body_lower = body.lower()
            for kw in _REPLACE_KEYWORDS:
                if kw in body_lower:
                    return True
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)
        return False

    async def is_upload_required_on_page(self, page: Page, container=None) -> bool:
        """
        Return True if the current page contains a visible upload widget.
        Used by the form engine to decide whether upload is a required checkpoint.
        """
        scope = container if container is not None else page

        # Check standard file inputs
        for selector in _FILE_INPUT_SELECTORS:
            try:
                count = await scope.locator(selector).count()
                if count > 0:
                    return True
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

        # Check visible upload trigger buttons
        for selector in _UPLOAD_TRIGGER_SELECTORS[
            :10
        ]:  # check first 10 (most specific)
            try:
                el = scope.locator(selector).first
                if await el.count() > 0 and await el.is_visible():
                    return True
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

        # Check via JS for shadow DOM file inputs
        try:
            found = await page.evaluate("""
                () => {
                    function findFileInputs(root) {
                        let found = false;
                        const all = root.querySelectorAll('*');
                        for (const el of all) {
                            if (el.shadowRoot) {
                                if (findFileInputs(el.shadowRoot)) return true;
                            }
                            if (el.tagName === 'INPUT' && el.type === 'file') return true;
                        }
                        return false;
                    }
                    return findFileInputs(document);
                }
            """)
            if found:
                return True
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)

        return False

    async def is_upload_already_verified(self, page: Page, filename: str) -> bool:
        """
        Return True if page already shows signs of a completed upload
        (filename visible, delete button, progress complete, etc.).
        Uses same logic as _verify_upload but without timeout waiting.
        """
        # Check session state first
        if self._upload_verified:
            return True
        # Quick DOM check
        try:
            body = await page.inner_text("body", timeout=2000)
            body_l = body.lower()
            stem = Path(filename).stem.lower()
            if filename.lower() in body_l or stem in body_l:
                return True
            for kw in ["delete", "remove", "replace", "re-upload"]:
                # These buttons appearing near a file name = upload done
                if kw in body_l:
                    return True
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)
        return False

    # ── Strategy Executor ─────────────────────────────────────────────────────

    async def _execute_strategy(
        self,
        strategy: UploadStrategy,
        page: Page,
        container,
        path: str,
        filename: str,
        profile=None,
    ) -> UploadResult:
        if strategy == UploadStrategy.SHADOW_DOM:
            return await self._strategy_shadow_dom(page, path, filename)
        elif strategy == UploadStrategy.IFRAME_SEARCH:
            return await self._strategy_iframe_search(page, path, filename)
        elif strategy == UploadStrategy.REACT_HIDDEN:
            return await self._strategy_react_hidden(page, path, filename)
        elif strategy == UploadStrategy.DRAG_DROP:
            return await self._strategy_drag_drop(page, path, filename)
        elif strategy == UploadStrategy.ARIA_BUTTON:
            return await self._strategy_aria_button(page, container, path, filename)
        elif strategy == UploadStrategy.DIRECT:
            return await self._strategy_direct(page, container, path, filename, profile)
        elif strategy == UploadStrategy.FILE_CHOOSER:
            return await self._strategy_file_chooser(
                page, container, path, filename, profile
            )
        elif strategy == UploadStrategy.REVEAL:
            return await self._strategy_reveal_hidden(page, container, path, filename)
        elif strategy == UploadStrategy.WINDOWS_UI:
            return await self._strategy_windows_ui(page, path, filename, profile)
        return UploadResult(success=False, failure_reason="Unknown strategy")

    # ── Strategy 1: Shadow DOM traversal ─────────────────────────────────────

    async def _strategy_shadow_dom(
        self, page: Page, path: str, filename: str
    ) -> UploadResult:
        """
        Traverse all shadow roots recursively via JS to find file inputs,
        then use CDP to set the file directly on the element.
        """
        try:
            # Find all file inputs including those inside shadow roots
            # Returns list of element handles by injecting into shadow trees
            result = await page.evaluate(
                """
                (resumePath) => {
                    function findAndSetFile(root, path) {
                        const all = root.querySelectorAll('*');
                        for (const el of all) {
                            if (el.shadowRoot) {
                                const found = findAndSetFile(el.shadowRoot, path);
                                if (found) return found;
                            }
                            if (el.tagName === 'INPUT' && el.type === 'file') {
                                return { found: true, id: el.id, name: el.name, index: -1 };
                            }
                        }
                        return null;
                    }
                    return findAndSetFile(document, resumePath);
                }
            """,
                path,
            )

            if not result:
                return UploadResult(
                    success=False,
                    strategy_used=UploadStrategy.SHADOW_DOM,
                    failure_reason="No file inputs found in shadow DOM",
                )

            # Use CDP to set file on the found element
            client = await page.context.new_cdp_session(page)
            try:
                # Get all file input nodes via CDP DOM
                doc = await client.send(
                    "DOM.getDocument", {"depth": -1, "pierce": True}
                )
                root_node_id = doc["root"]["nodeId"]

                # Search for file inputs including inside shadow DOM via pierce
                file_inputs = await client.send(
                    "DOM.querySelectorAll",
                    {"nodeId": root_node_id, "selector": "input[type='file']"},
                )

                if file_inputs and file_inputs.get("nodeIds"):
                    node_id = file_inputs["nodeIds"][0]
                    await client.send(
                        "DOM.setFileInputFiles",
                        {"nodeId": node_id, "files": [str(Path(path).resolve())]},
                    )
                    logger.info(
                        "UploadManager [SHADOW_DOM]: CDP setFileInputFiles succeeded"
                    )
                    return UploadResult(
                        success=True, strategy_used=UploadStrategy.SHADOW_DOM
                    )
            finally:
                try:
                    await client.detach()
                except Exception as _exc:
                    logger.debug("Suppressed: %s", _exc)

        except Exception as exc:
            logger.debug("UploadManager [SHADOW_DOM]: failed: %s", exc)

        return UploadResult(
            success=False,
            strategy_used=UploadStrategy.SHADOW_DOM,
            failure_reason="Shadow DOM CDP upload failed",
        )

    # ── Strategy 2: iframe search ─────────────────────────────────────────────

    async def _strategy_iframe_search(
        self, page: Page, path: str, filename: str
    ) -> UploadResult:
        """Search all iframes (including nested) for file inputs."""
        try:
            frames = page.frames
            for frame in frames:
                if frame == page.main_frame:
                    continue
                try:
                    inputs = frame.locator("input[type='file']")
                    count = await inputs.count()
                    if count == 0:
                        continue
                    for i in range(count):
                        f_input = inputs.nth(i)
                        try:
                            await f_input.set_input_files(path)
                            logger.info(
                                "UploadManager [IFRAME]: set_input_files on frame '%s' input #%d",
                                frame.url[:60],
                                i,
                            )
                            return UploadResult(
                                success=True, strategy_used=UploadStrategy.IFRAME_SEARCH
                            )
                        except Exception as exc:
                            logger.debug(
                                "UploadManager [IFRAME]: input #%d failed: %s", i, exc
                            )
                except Exception as exc:
                    logger.debug("UploadManager [IFRAME]: frame error: %s", exc)

            # Also try frame_locator approach for named/src iframes
            iframe_selectors = [
                "iframe[src*='apply']",
                "iframe[src*='greenhouse']",
                "iframe[src*='lever']",
                "iframe[src*='workday']",
                "iframe[src*='ashby']",
                "iframe[src*='icims']",
                "iframe[title*='application']",
                "iframe[title*='apply']",
                "iframe",
            ]
            for iframe_sel in iframe_selectors:
                try:
                    frame_loc = page.frame_locator(iframe_sel)
                    inputs = frame_loc.locator("input[type='file']")
                    count = await inputs.count()
                    if count > 0:
                        await inputs.first.set_input_files(path)
                        logger.info(
                            "UploadManager [IFRAME]: set_input_files via frame_locator '%s'",
                            iframe_sel,
                        )
                        return UploadResult(
                            success=True, strategy_used=UploadStrategy.IFRAME_SEARCH
                        )
                except Exception:
                    continue

        except Exception as exc:
            logger.debug("UploadManager [IFRAME]: outer error: %s", exc)

        return UploadResult(
            success=False,
            strategy_used=UploadStrategy.IFRAME_SEARCH,
            failure_reason="No file inputs found in any iframe",
        )

    # ── Strategy 3: React hidden input ───────────────────────────────────────

    async def _strategy_react_hidden(
        self, page: Page, path: str, filename: str
    ) -> UploadResult:
        """
        React/Angular/Vue apps often have hidden file inputs managed by JS frameworks.
        Use CDP to set files directly, bypassing display:none / visibility:hidden.
        Then dispatch synthetic change events to trigger the framework's handler.
        """
        try:
            abs_path = str(Path(path).resolve())
            client = await page.context.new_cdp_session(page)
            try:
                doc = await client.send(
                    "DOM.getDocument", {"depth": -1, "pierce": True}
                )
                root_node_id = doc["root"]["nodeId"]

                file_inputs = await client.send(
                    "DOM.querySelectorAll",
                    {"nodeId": root_node_id, "selector": "input[type='file']"},
                )

                node_ids = file_inputs.get("nodeIds", [])
                if not node_ids:
                    return UploadResult(
                        success=False,
                        strategy_used=UploadStrategy.REACT_HIDDEN,
                        failure_reason="No file inputs found via CDP",
                    )

                for node_id in node_ids:
                    try:
                        await client.send(
                            "DOM.setFileInputFiles",
                            {"nodeId": node_id, "files": [abs_path]},
                        )
                        # Dispatch change + input events for React/Vue/Angular
                        await page.evaluate(
                            """
                            (nodeId) => {
                                const inputs = document.querySelectorAll('input[type="file"]');
                                for (const inp of inputs) {
                                    try {
                                        const ev1 = new Event('change', { bubbles: true });
                                        const ev2 = new Event('input', { bubbles: true });
                                        inp.dispatchEvent(ev1);
                                        inp.dispatchEvent(ev2);
                                        // React fiber event
                                        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                                            window.HTMLInputElement.prototype, 'value'
                                        );
                                        if (nativeInputValueSetter) {
                                            nativeInputValueSetter.set.call(inp, inp.value);
                                        }
                                    } catch(e) {}
                                }
                            }
                        """,
                            node_id,
                        )

                        logger.info(
                            "UploadManager [REACT]: CDP set + event dispatch succeeded for node %d",
                            node_id,
                        )
                        return UploadResult(
                            success=True, strategy_used=UploadStrategy.REACT_HIDDEN
                        )
                    except Exception as exc:
                        logger.debug(
                            "UploadManager [REACT]: node %d failed: %s", node_id, exc
                        )
            finally:
                try:
                    await client.detach()
                except Exception as _exc:
                    logger.debug("Suppressed: %s", _exc)

        except Exception as exc:
            logger.debug("UploadManager [REACT]: outer error: %s", exc)

        return UploadResult(
            success=False,
            strategy_used=UploadStrategy.REACT_HIDDEN,
            failure_reason="React hidden input CDP approach failed",
        )

    # ── Strategy 4: Drag-and-drop simulation ─────────────────────────────────

    async def _strategy_drag_drop(
        self, page: Page, path: str, filename: str
    ) -> UploadResult:
        """
        Simulate drag-and-drop file upload for Dropzone.js, FilePond, Uppy, and
        custom drag-drop zones by creating a DataTransfer object via JS.
        """
        abs_path = str(Path(path).resolve())

        # Selectors for common drag-drop zones
        dropzone_selectors = [
            "[class*='dropzone']",
            "[class*='drop-zone']",
            "[class*='drop_zone']",
            "[class*='file-drop']",
            "[class*='filepond']",
            "[class*='uppy-drop']",
            "[class*='dz-clickable']",
            "[class*='upload-zone']",
            "[class*='drag-drop']",
            "[class*='dragdrop']",
            "div[aria-label*='drag' i]",
            "div[aria-label*='drop' i]",
            "div[data-testid*='drop']",
            "div[data-test*='drop']",
        ]

        for selector in dropzone_selectors:
            try:
                el = page.locator(selector).first
                if await el.count() == 0 or not await el.is_visible():
                    continue

                # Read file content and simulate drop
                with open(abs_path, "rb") as f:
                    file_content = f.read()

                import base64

                file_b64 = base64.b64encode(file_content).decode()
                mime = (
                    "application/pdf"
                    if path.endswith(".pdf")
                    else "application/octet-stream"
                )

                result = await page.evaluate(
                    """
                    async ([selector, filename, fileB64, mimeType]) => {
                        const el = document.querySelector(selector);
                        if (!el) return false;
                        try {
                            const bytes = Uint8Array.from(atob(fileB64), c => c.charCodeAt(0));
                            const blob = new Blob([bytes], { type: mimeType });
                            const file = new File([blob], filename, { type: mimeType });
                            const dt = new DataTransfer();
                            dt.items.add(file);
                            const events = ['dragenter', 'dragover', 'drop'];
                            for (const evName of events) {
                                const ev = new DragEvent(evName, {
                                    bubbles: true,
                                    cancelable: true,
                                    dataTransfer: dt
                                });
                                el.dispatchEvent(ev);
                                await new Promise(r => setTimeout(r, 100));
                            }
                            return true;
                        } catch(e) {
                            return false;
                        }
                    }
                """,
                    [selector, filename, file_b64, mime],
                )

                if result:
                    logger.info(
                        "UploadManager [DRAG_DROP]: DataTransfer drop simulated on '%s'",
                        selector,
                    )
                    await asyncio.sleep(1.0)  # allow zone to process
                    return UploadResult(
                        success=True, strategy_used=UploadStrategy.DRAG_DROP
                    )

            except Exception as exc:
                logger.debug(
                    "UploadManager [DRAG_DROP]: selector '%s' failed: %s", selector, exc
                )

        return UploadResult(
            success=False,
            strategy_used=UploadStrategy.DRAG_DROP,
            failure_reason="No drag-drop zones found or simulation failed",
        )

    # ── Strategy 5: ARIA button → FileChooser ────────────────────────────────

    async def _strategy_aria_button(
        self, page: Page, container, path: str, filename: str
    ) -> UploadResult:
        """
        Find ARIA-labeled upload buttons (including SVG buttons and icon buttons)
        and use FileChooser interception.
        """
        scope = container if container is not None else page

        aria_selectors = [
            "[aria-label*='upload' i]",
            "[aria-label*='attach' i]",
            "[aria-label*='browse' i]",
            "[aria-label*='choose file' i]",
            "[title*='upload' i]",
            "[title*='attach' i]",
            "button svg[aria-label*='upload' i]",
            "span[role='button'][aria-label*='upload' i]",
            "div[role='button'][aria-label*='upload' i]",
        ]

        for selector in aria_selectors:
            try:
                el = scope.locator(selector).first
                if await el.count() == 0:
                    continue
                visible = False
                try:
                    visible = await el.is_visible()
                except Exception as _exc:
                    logger.debug("Suppressed: %s", _exc)

                if not visible:
                    continue

                try:
                    async with page.expect_file_chooser(
                        timeout=_CHOOSER_TIMEOUT_MS
                    ) as chooser_info:
                        await el.click()
                    chooser: FileChooser = await chooser_info.value
                    await chooser.set_files(path)
                    logger.info(
                        "UploadManager [ARIA]: FileChooser.set_files() via aria button '%s'",
                        selector,
                    )
                    return UploadResult(
                        success=True, strategy_used=UploadStrategy.ARIA_BUTTON
                    )
                except asyncio.TimeoutError:
                    logger.debug(
                        "UploadManager [ARIA]: chooser timeout for '%s'", selector
                    )
                except Exception as exc:
                    logger.debug(
                        "UploadManager [ARIA]: '%s' click failed: %s", selector, exc
                    )
            except Exception:
                continue

        return UploadResult(
            success=False,
            strategy_used=UploadStrategy.ARIA_BUTTON,
            failure_reason="No ARIA upload buttons found",
        )

    # ── Strategy 6: Direct file input ─────────────────────────────────────────

    async def _strategy_direct(
        self, page: Page, container, path: str, filename: str, profile=None
    ) -> UploadResult:
        scope = container if container is not None else page

        selectors = []
        if profile and profile.file_input_selectors:
            selectors.extend(profile.file_input_selectors)
        for s in _FILE_INPUT_SELECTORS:
            if s not in selectors:
                selectors.append(s)

        for selector in selectors:
            try:
                inputs = scope.locator(selector)
                count = await inputs.count()
                if count == 0:
                    continue
                for i in range(count):
                    f_input = inputs.nth(i)
                    try:
                        await f_input.set_input_files(path)
                        logger.info(
                            "UploadManager [DIRECT]: set_input_files() on selector '%s' (#%d)",
                            selector,
                            i,
                        )
                        return UploadResult(
                            success=True, strategy_used=UploadStrategy.DIRECT
                        )
                    except Exception as exc:
                        logger.debug(
                            "UploadManager [DIRECT]: input %d with '%s' failed: %s",
                            i,
                            selector,
                            exc,
                        )
            except Exception as exc:
                logger.debug(
                    "UploadManager [DIRECT]: selector '%s' error: %s", selector, exc
                )

        return UploadResult(
            success=False,
            strategy_used=UploadStrategy.DIRECT,
            failure_reason="No file input element found in DOM",
        )

    # ── Strategy 7: FileChooser interception ──────────────────────────────────

    async def _strategy_file_chooser(
        self, page: Page, container, path: str, filename: str, profile=None
    ) -> UploadResult:
        scope = container if container is not None else page

        trigger_selectors = []
        if profile and profile.trigger_selectors:
            trigger_selectors.extend(profile.trigger_selectors)
        for s in _UPLOAD_TRIGGER_SELECTORS:
            if s not in trigger_selectors:
                trigger_selectors.append(s)

        trigger_locator: Locator | None = None
        trigger_selector: str = ""

        for selector in trigger_selectors:
            try:
                el = scope.locator(selector).first
                count = await el.count()
                if count > 0 and await el.is_visible():
                    trigger_locator = el
                    trigger_selector = selector
                    break
            except Exception:
                continue

        if trigger_locator is None:
            return UploadResult(
                success=False,
                strategy_used=UploadStrategy.FILE_CHOOSER,
                failure_reason="No upload trigger button found for FileChooser interception",
            )

        logger.info(
            "UploadManager [CHOOSER]: found trigger '%s' — expecting FileChooser",
            trigger_selector,
        )

        try:
            async with page.expect_file_chooser(
                timeout=_CHOOSER_TIMEOUT_MS
            ) as chooser_info:
                await trigger_locator.click()
            chooser: FileChooser = await chooser_info.value
            await chooser.set_files(path)
            logger.info(
                "UploadManager [CHOOSER]: FileChooser.set_files() completed for '%s'",
                filename,
            )
            return UploadResult(success=True, strategy_used=UploadStrategy.FILE_CHOOSER)
        except asyncio.TimeoutError:
            return UploadResult(
                success=False,
                strategy_used=UploadStrategy.FILE_CHOOSER,
                failure_reason="FileChooser event did not fire within timeout",
            )
        except Exception as exc:
            return UploadResult(
                success=False,
                strategy_used=UploadStrategy.FILE_CHOOSER,
                failure_reason=str(exc),
            )

    # ── Strategy 8: Reveal hidden file input ──────────────────────────────────

    async def _strategy_reveal_hidden(
        self, page: Page, container, path: str, filename: str
    ) -> UploadResult:
        try:
            all_inputs_info: list = await page.evaluate("""
                () => {
                    const inputs = Array.from(document.querySelectorAll('input[type="file"]'));
                    return inputs.map((el, idx) => ({
                        idx,
                        id: el.id || '',
                        name: el.name || '',
                        display: el.style.display,
                        visibility: el.style.visibility,
                        opacity: el.style.opacity,
                        computedDisplay: window.getComputedStyle(el).display,
                        computedVisibility: window.getComputedStyle(el).visibility,
                    }));
                }
            """)

            if not all_inputs_info:
                return UploadResult(
                    success=False,
                    strategy_used=UploadStrategy.REVEAL,
                    failure_reason="No file inputs found in DOM to reveal",
                )

            logger.info(
                "UploadManager [REVEAL]: found %d file input(s) to try revealing",
                len(all_inputs_info),
            )

            for info in all_inputs_info:
                idx = info["idx"]
                try:
                    await page.evaluate(f"""
                        () => {{
                            const inputs = document.querySelectorAll('input[type="file"]');
                            const el = inputs[{idx}];
                            if (!el) return;
                            el.style.display = 'block';
                            el.style.visibility = 'visible';
                            el.style.opacity = '1';
                            el.style.width = '1px';
                            el.style.height = '1px';
                            el.style.position = 'fixed';
                            el.style.top = '0';
                            el.style.left = '0';
                            el.style.zIndex = '9999';
                        }}
                    """)

                    await asyncio.sleep(_REVEAL_RESTORE_DELAY)

                    f_input = page.locator("input[type='file']").nth(idx)
                    await f_input.set_input_files(path)

                    await page.evaluate(f"""
                        () => {{
                            const inputs = document.querySelectorAll('input[type="file"]');
                            const el = inputs[{idx}];
                            if (!el) return;
                            el.style.display = '{info.get("display", "")}';
                            el.style.visibility = '{info.get("visibility", "")}';
                            el.style.opacity = '{info.get("opacity", "")}';
                            el.style.width = '';
                            el.style.height = '';
                            el.style.position = '';
                            el.style.top = '';
                            el.style.left = '';
                            el.style.zIndex = '';
                        }}
                    """)

                    logger.info(
                        "UploadManager [REVEAL]: revealed input #%d and uploaded '%s'",
                        idx,
                        filename,
                    )
                    return UploadResult(
                        success=True, strategy_used=UploadStrategy.REVEAL
                    )

                except Exception as exc:
                    logger.debug(
                        "UploadManager [REVEAL]: input #%d failed: %s", idx, exc
                    )
                    try:
                        await page.evaluate(f"""
                            () => {{
                                const inputs = document.querySelectorAll('input[type="file"]');
                                const el = inputs[{idx}];
                                if (el) {{
                                    el.style.display = '{info.get("display", "")}';
                                    el.style.visibility = '{info.get("visibility", "")}';
                                    el.style.opacity = '{info.get("opacity", "")}';
                                }}
                            }}
                        """)
                    except Exception as _exc:
                        logger.debug("Suppressed: %s", _exc)

            return UploadResult(
                success=False,
                strategy_used=UploadStrategy.REVEAL,
                failure_reason=f"All {len(all_inputs_info)} revealed file inputs failed",
            )

        except Exception as exc:
            return UploadResult(
                success=False,
                strategy_used=UploadStrategy.REVEAL,
                failure_reason=str(exc),
            )

    # ── Strategy 9: Windows UI Automation (pywinauto) ─────────────────────────

    async def _strategy_windows_ui(
        self, page: Page, path: str, filename: str, profile=None
    ) -> UploadResult:
        # Check if pywinauto is available
        try:
            from automation.dependency_guard import is_winui_available

            if not is_winui_available():
                return UploadResult(
                    success=False,
                    strategy_used=UploadStrategy.WINDOWS_UI,
                    failure_reason="pywinauto not available (install failed or disabled)",
                )
        except ImportError:
            pass

        logger.warning(
            "UploadManager [WINUI]: falling back to Windows UI Automation. "
            "This means no browser-based upload method was found.",
        )

        try:
            import pywinauto  # type: ignore # noqa: F401
        except ImportError:
            return UploadResult(
                success=False,
                strategy_used=UploadStrategy.WINDOWS_UI,
                failure_reason="pywinauto not installed",
            )

        # Try to open file dialog by clicking upload trigger
        try:
            trigger = None
            trigger_selectors = []
            if profile and profile.trigger_selectors:
                trigger_selectors.extend(profile.trigger_selectors)
            trigger_selectors.extend(_UPLOAD_TRIGGER_SELECTORS)

            for selector in trigger_selectors:
                try:
                    el = page.locator(selector).first
                    if await el.count() > 0 and await el.is_visible():
                        trigger = el
                        break
                except Exception:
                    continue

            if trigger:
                await trigger.click()
                logger.info(
                    "UploadManager [WINUI]: clicked upload trigger to open OS dialog"
                )
        except Exception as exc:
            logger.warning("UploadManager [WINUI]: trigger click failed: %s", exc)

        await asyncio.sleep(1.5)

        result = await asyncio.to_thread(self._interact_with_win_dialog, path, filename)
        return result

    def _interact_with_win_dialog(self, path: str, filename: str) -> UploadResult:
        """Synchronous pywinauto interaction (runs in a thread)."""
        try:
            from pywinauto import Desktop  # type: ignore
            from pywinauto.keyboard import send_keys  # type: ignore

            abs_path = str(Path(path).resolve())
            desktop = Desktop(backend="uia")

            dialog = None
            for _ in range(10):
                try:
                    windows = desktop.windows()
                    for w in windows:
                        try:
                            title = w.window_text().lower()
                            cls = w.class_name()
                            if cls == "#32770" or any(
                                kw in title
                                for kw in ["open", "upload", "choose", "browse", "file"]
                            ):
                                dialog = w
                                break
                        except Exception:
                            continue
                    if dialog:
                        break
                except Exception as _exc:
                    logger.debug("Suppressed: %s", _exc)
                time.sleep(0.3)

            if dialog is None:
                return UploadResult(
                    success=False,
                    strategy_used=UploadStrategy.WINDOWS_UI,
                    failure_reason="Windows file dialog not found within timeout",
                )

            filename_edit = None
            try:
                filename_edit = dialog.child_window(control_type="Edit", found_index=0)
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

            if filename_edit is None:
                return UploadResult(
                    success=False,
                    strategy_used=UploadStrategy.WINDOWS_UI,
                    failure_reason="Could not find filename edit control in dialog",
                )

            filename_edit.set_focus()
            filename_edit.set_edit_text(abs_path)
            time.sleep(0.2)

            try:
                open_btn = dialog.child_window(title="Open", control_type="Button")
                open_btn.click()
            except Exception:
                send_keys("{ENTER}")

            time.sleep(0.8)
            logger.info(
                "UploadManager [WINUI]: submitted path via Windows UI dialog → '%s'",
                abs_path,
            )
            return UploadResult(success=True, strategy_used=UploadStrategy.WINDOWS_UI)

        except Exception as exc:
            logger.error("UploadManager [WINUI]: interaction failed: %s", exc)
            return UploadResult(
                success=False,
                strategy_used=UploadStrategy.WINDOWS_UI,
                failure_reason=str(exc),
            )

    # ── Upload Verification ───────────────────────────────────────────────────

    async def _verify_upload(self, page: Page, filename: str, profile=None) -> bool:
        """
        Verify upload success using multiple signals.
        Any ONE signal passing = success.

        Signals checked:
          1. Site-specific verify selectors
          2. Filename/stem visible in page body
          3. Progress element at 100%
          4. Delete/Replace/Remove button visible near upload area
          5. input[type=file].files.length > 0 (JS check)
          6. Generic success keywords
          7. Upload error keywords (negative signal)
        """
        stem = Path(filename).stem
        deadline = time.monotonic() + _VERIFY_TIMEOUT_S

        # Signal 1: site-specific selectors
        if profile and profile.verify_selectors:
            for v_sel in profile.verify_selectors:
                try:
                    el = page.locator(v_sel)
                    if await el.count() > 0:
                        logger.info(
                            "UploadManager: verification PASSED via site selector '%s'",
                            v_sel,
                        )
                        return True
                except Exception as _exc:
                    logger.debug("Suppressed: %s", _exc)

        while time.monotonic() < deadline:
            try:
                body = await page.inner_text("body", timeout=2000)
                body_l = body.lower()

                # Negative signal: upload error
                if any(kw in body_l for kw in _UPLOAD_ERROR_KEYWORDS):
                    logger.warning(
                        "UploadManager: upload error keyword detected — upload failed."
                    )
                    return False

                # Signal 2: filename visible
                if filename.lower() in body_l or stem.lower() in body_l:
                    logger.info(
                        "UploadManager: verification PASSED — filename visible in DOM"
                    )
                    return True

                # Signal 3: generic success keywords
                if any(kw in body_l for kw in _UPLOAD_SUCCESS_KEYWORDS):
                    logger.info(
                        "UploadManager: verification PASSED — success keyword in DOM"
                    )
                    return True

                # Signal 4: delete/replace/remove button appeared
                for kw in ["delete", "remove file", "replace resume", "change file"]:
                    if kw in body_l:
                        logger.info(
                            "UploadManager: verification PASSED — '%s' button found in DOM",
                            kw,
                        )
                        return True

            except Exception as exc:
                logger.debug("UploadManager: verification check error: %s", exc)

            # Signal 5: JS check — input[type=file].files.length > 0
            try:
                has_files = await page.evaluate("""
                    () => {
                        const inputs = document.querySelectorAll('input[type="file"]');
                        for (const inp of inputs) {
                            if (inp.files && inp.files.length > 0) return true;
                        }
                        return false;
                    }
                """)
                if has_files:
                    logger.info(
                        "UploadManager: verification PASSED — input.files.length > 0"
                    )
                    return True
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

            # Signal 6: progress element at 100%
            try:
                progress_done = await page.evaluate("""
                    () => {
                        const bars = document.querySelectorAll(
                            'progress[value="100"], [role="progressbar"][aria-valuenow="100"], ' +
                            '[class*="progress"][class*="complete"], [class*="upload-complete"]'
                        );
                        return bars.length > 0;
                    }
                """)
                if progress_done:
                    logger.info("UploadManager: verification PASSED — progress at 100%")
                    return True
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

            await asyncio.sleep(0.5)

        logger.warning(
            "UploadManager: verification TIMEOUT (%.1fs) — filename '%s' not confirmed in DOM.",
            _VERIFY_TIMEOUT_S,
            filename,
        )
        return False

    # ── Strategy Order ────────────────────────────────────────────────────────

    def _get_strategy_order(
        self, site: str, profile=None, db_preferred: UploadStrategy | None = None
    ) -> list[UploadStrategy]:
        """
        Return the ordered list of strategies to attempt.
        Preferred strategy (from DB, session cache, or profile) goes first.
        """
        default_order = [
            UploadStrategy.SHADOW_DOM,
            UploadStrategy.IFRAME_SEARCH,
            UploadStrategy.REACT_HIDDEN,
            UploadStrategy.DRAG_DROP,
            UploadStrategy.ARIA_BUTTON,
            UploadStrategy.DIRECT,
            UploadStrategy.FILE_CHOOSER,
            UploadStrategy.REVEAL,
            UploadStrategy.WINDOWS_UI,
        ]

        preferred: UploadStrategy | None = None

        if db_preferred:
            preferred = db_preferred
        else:
            cached = self._site_strategy_cache.get(site.lower())
            if cached:
                preferred = cached
            elif profile and profile.preferred_strategy:
                try:
                    preferred = UploadStrategy[profile.preferred_strategy]
                except (KeyError, ValueError):
                    pass

        if preferred:
            return [preferred] + [s for s in default_order if s != preferred]
        return default_order


# ── Singleton Factories ───────────────────────────────────────────────────────

_resume_manager: ResumeManager | None = None
_upload_manager: UploadManager | None = None


def get_resume_manager() -> ResumeManager:
    """Return the application-wide singleton ResumeManager (lazy-initialized)."""
    global _resume_manager
    if _resume_manager is None:
        _resume_manager = ResumeManager()
    return _resume_manager


def get_upload_manager() -> UploadManager:
    """Return the application-wide singleton UploadManager (lazy-initialized)."""
    global _upload_manager
    if _upload_manager is None:
        _upload_manager = UploadManager(get_resume_manager())
    return _upload_manager
