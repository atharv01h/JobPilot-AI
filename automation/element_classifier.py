"""
element_classifier.py — DOM preprocessor and semantic element classifier.

Extracts only visible interactive elements, ignoring decorative wrappers and hidden tags.
"""

from __future__ import annotations

from playwright.async_api import Page

from core.logger import get_logger

logger = get_logger(__name__)

# Javascript to run inside browser context
_JS_SCANNER = """
(() => {
    const getSemanticElements = () => {
        const isVisible = (el) => {
            if (!el.getBoundingClientRect) return false;
            const rect = el.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) return false;
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
            return true;
        };

        const isJobCard = (el) => {
            const hostname = window.location.hostname;
            if (hostname.includes('linkedin.com')) {
                return el.matches('li.jobs-search-results-list__list-item, .job-card-container, [data-occludable-job-id]');
            }
            if (hostname.includes('naukri.com')) {
                return el.matches('article.jobTuple, div.cust-job-tuple, [class*="jobTuple"]');
            }
            if (hostname.includes('indeed.com')) {
                return el.matches('div.job_seen_beacon, td.resultContent, .slider_container');
            }
            if (hostname.includes('foundit.in')) {
                return el.matches('div.cardContent, div.job-tuple, [class*="job-tuple"]');
            }
            if (hostname.includes('glassdoor.')) {
                return el.matches("li[data-test='jobListing'], .JobCard_jobCardContainer__");
            }
            if (hostname.includes('instahyre.com')) {
                return el.matches(".job-card, .job-description, [class*='job-card']");
            }
            if (hostname.includes('wellfound.com')) {
                return el.matches("[class*='JobCard'], [data-test='JobResult']");
            }
            return false;
        };

        const getAccessibilityName = (el) => {
            let name = el.getAttribute('aria-label') || el.getAttribute('title') || '';
            if (name) return name.trim();
            
            const labelledBy = el.getAttribute('aria-labelledby');
            if (labelledBy) {
                const labelEl = document.getElementById(labelledBy);
                if (labelEl && labelEl.innerText) return labelEl.innerText.trim();
            }

            if (el.labels && el.labels.length > 0) {
                for (const l of el.labels) {
                    if (l.innerText) return l.innerText.trim();
                }
            }
            
            const placeholder = el.getAttribute('placeholder');
            if (placeholder) return placeholder.trim();

            const nameAttr = el.getAttribute('name');
            if (nameAttr) return nameAttr;

            if (el.innerText) {
                const txt = el.innerText.trim();
                if (txt.length > 0) return txt.slice(0, 100);
            }

            return '';
        };

        const classify = (el) => {
            const tag = el.tagName.toLowerCase();
            const type = el.getAttribute('type') ? el.getAttribute('type').toLowerCase() : '';
            const role = el.getAttribute('role') ? el.getAttribute('role').toLowerCase() : '';
            const text = (el.innerText || '').toLowerCase();
            const placeholder = (el.getAttribute('placeholder') || '').toLowerCase();
            const name = (el.getAttribute('name') || '').toLowerCase();

            if (isJobCard(el)) {
                return { role: 'Job card', confidence: 1.0 };
            }

            if (tag === 'form') {
                return { role: 'Form', confidence: 1.0 };
            }

            if (role === 'navigation' || tag === 'nav' || text.includes('next') || text.includes('previous') || el.matches('.pagination, [class*="pagination"]')) {
                if (tag === 'a' || tag === 'button' || el.matches('.page-link, [class*="page-"]')) {
                    return { role: 'Pagination', confidence: 0.9 };
                }
            }

            if (tag === 'input' && type === 'file') {
                return { role: 'Upload control', confidence: 1.0 };
            }
            if (tag === 'button' || tag === 'a' || role === 'button') {
                if (text.includes('upload') || text.includes('resume') || text.includes('cv') || text.includes('attach')) {
                    return { role: 'Upload control', confidence: 0.85 };
                }
            }

            if (tag === 'select' || role === 'combobox' || role === 'listbox' || el.matches('.select2, [class*="select"]')) {
                return { role: 'Dropdown', confidence: 1.0 };
            }

            if (tag === 'input' && type === 'checkbox') {
                return { role: 'Checkbox', confidence: 1.0 };
            }

            if (tag === 'input' && type === 'radio') {
                return { role: 'Radio', confidence: 1.0 };
            }

            if (tag === 'input' && (type === 'search' || name.includes('search') || placeholder.includes('search') || placeholder.includes('keyword') || placeholder.includes('location'))) {
                return { role: 'Search box', confidence: 0.95 };
            }

            if (tag === 'textarea' || el.isContentEditable) {
                return { role: 'Textbox', confidence: 1.0 };
            }
            if (tag === 'input') {
                if (['text', 'email', 'password', 'tel', 'number', 'url'].includes(type) || !type) {
                    return { role: 'Textbox', confidence: 0.9 };
                }
            }

            if (tag === 'button' || role === 'button' || ['submit', 'button', 'reset'].includes(type)) {
                return { role: 'Button', confidence: 1.0 };
            }

            if (tag === 'a' || role === 'link' || el.getAttribute('href')) {
                return { role: 'Link', confidence: 0.95 };
            }

            if (tag === 'label' || el.matches('.label, [class*="label-text"]')) {
                return { role: 'Visible label', confidence: 0.9 };
            }

            const cursor = window.getComputedStyle(el).cursor;
            if (cursor === 'pointer') {
                if (el.innerText && el.innerText.trim().length > 0 && el.children.length === 0) {
                    return { role: 'Button', confidence: 0.75 };
                }
            }

            return null;
        };

        const getSelector = (el) => {
            if (el.id) return `#${el.id}`;
            let selector = el.tagName.toLowerCase();
            if (el.getAttribute('class')) {
                const classes = el.getAttribute('class').trim().split(/\\s+/).filter(c => !c.includes(':') && c.length > 0).slice(0, 3);
                if (classes.length > 0) {
                    selector += '.' + classes.join('.');
                }
            }
            if (el.getAttribute('name')) {
                selector += `[name="${el.getAttribute('name')}"]`;
            }
            return selector;
        };

        const all = document.querySelectorAll('*');
        const result = [];
        let index = 0;

        for (const el of all) {
            if (!isVisible(el)) continue;
            const classification = classify(el);
            if (!classification) continue;

            const rect = el.getBoundingClientRect();
            const enabled = !el.disabled && !el.hasAttribute('disabled');
            const accName = getAccessibilityName(el);

            result.push({
                index: index++,
                tag: el.tagName.toLowerCase(),
                role: classification.role,
                text: el.innerText ? el.innerText.trim().slice(0, 100) : (el.value ? el.value.trim().slice(0, 100) : ''),
                accessibilityName: accName,
                visibility: true,
                enabled: enabled,
                confidence: classification.confidence,
                selector: getSelector(el),
                bounds: {
                    x: rect.left + window.scrollX,
                    y: rect.top + window.scrollY,
                    width: rect.width,
                    height: rect.height
                }
            });
        }
        return result;
    };
    return getSemanticElements();
})()
"""

# Simplified fallback scanner in case main V8 parsing crashes
_JS_FALLBACK = """
(() => {
    try {
        const elements = [];
        let index = 0;
        const tags = ['input', 'button', 'a', 'select', 'textarea'];
        for (const tag of tags) {
            const els = document.querySelectorAll(tag);
            for (const el of els) {
                try {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    if (rect.width === 0 || rect.height === 0 || style.display === 'none' || style.visibility === 'hidden') continue;
                    
                    let role = 'Textbox';
                    if (tag === 'button') role = 'Button';
                    else if (tag === 'a') role = 'Link';
                    else if (tag === 'select') role = 'Dropdown';
                    else if (tag === 'textarea') role = 'Textbox';
                    else {
                        const type = el.getAttribute('type') ? el.getAttribute('type').toLowerCase() : '';
                        if (type === 'checkbox') role = 'Checkbox';
                        else if (type === 'radio') role = 'Radio';
                        else if (['submit', 'button'].includes(type)) role = 'Button';
                        else if (type === 'search') role = 'Search box';
                    }
                    
                    elements.push({
                        index: index++,
                        tag: tag,
                        role: role,
                        text: el.innerText ? el.innerText.trim().slice(0, 100) : (el.value ? el.value.trim().slice(0, 100) : ''),
                        accessibilityName: el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('placeholder') || '',
                        visibility: true,
                        enabled: !el.disabled,
                        confidence: 0.5,
                        selector: tag + (el.id ? `#${el.id}` : ''),
                        bounds: {
                            x: rect.left + window.scrollX,
                            y: rect.top + window.scrollY,
                            width: rect.width,
                            height: rect.height
                        }
                    });
                } catch (e) {}
            }
        }
        return elements;
    } catch (e) {
        return [];
    }
})()
"""


def validate_and_wrap_script(script: str) -> str:
    """Ensures a script string is properly formatted and wrapped in an IIFE wrapper."""
    trimmed = script.strip()
    # If not formatted as IIFE, wrap it
    if not (
        trimmed.startswith(("(() =>", "(function")) or trimmed.endswith(")()")
    ):
        return f"(() => {{\n{trimmed}\n}})()"
    return trimmed


class ElementClassifier:
    """Preprocesses pages and classifies elements into semantic roles."""

    async def get_interactive_elements(self, page: Page) -> list[dict[str, Any]]:
        """
        Scan page and return a list of classified semantic elements.
        """
        # Validate and wrap the main scanner script
        script = validate_and_wrap_script(_JS_SCANNER)
        try:
            elements = await page.evaluate(script)
            logger.info(
                "DOM Preprocessor: Classified %d semantic elements.", len(elements)
            )
            return elements
        except Exception as exc:
            logger.error(
                "Failed to run DOM Preprocessor scan: %s. Trying fallback extractor...",
                exc,
            )
            try:
                fallback_script = validate_and_wrap_script(_JS_FALLBACK)
                elements = await page.evaluate(fallback_script)
                logger.info(
                    "DOM Preprocessor Fallback: Classified %d semantic elements.",
                    len(elements),
                )
                return elements
            except Exception as fallback_exc:
                logger.error("Fallback DOM Preprocessor also failed: %s", fallback_exc)
                return []

    async def find_element_by_role(
        self, page: Page, role: str, text_query: str
    ) -> dict[str, Any] | None:
        """
        Helper to locate an element with a matching role and text query.
        """
        elements = await self.get_interactive_elements(page)
        role_lower = role.lower()
        query_lower = text_query.lower()

        best_match = None
        for el in elements:
            if el["role"].lower() == role_lower:
                txt = (el["text"] or "").lower() or (
                    el["accessibilityName"] or ""
                ).lower()
                if query_lower in txt:
                    if query_lower == txt:
                        return el
                    best_match = el

        return best_match


# ── Singleton ─────────────────────────────────────────────────────────────────

_classifier: ElementClassifier | None = None


def get_element_classifier() -> ElementClassifier:
    global _classifier
    if _classifier is None:
        _classifier = ElementClassifier()
    return _classifier
