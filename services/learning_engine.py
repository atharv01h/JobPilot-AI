"""
learning_engine.py — V9 Persistent Learning Engine.

Saves successful selectors, question-answer pairs, and failure patterns
to the knowledge_memory SQLite table for continuous improvement.

Every successful action the agent completes is remembered.
Every failure pattern is recorded to prevent re-attempting dead strategies.
"""

from __future__ import annotations

import json
import time
from typing import Any

from core.logger import get_logger

logger = get_logger(__name__)

# Key prefixes for knowledge_memory entries
_KEY_SELECTOR = "learn:selector:"
_KEY_ANSWER = "learn:answer:"
_KEY_FAILURE = "learn:failure:"
_KEY_STATS = "learn:stats:"


class LearningEngine:
    """
    Reads and writes learned knowledge to the knowledge_memory SQLite table.

    All methods are async — they read/write through the shared database singleton.
    Failures during read/write are silently logged and never block task execution.
    """

    # ── Selector Learning ─────────────────────────────────────────────────────

    async def record_success(
        self,
        site: str,
        selector_type: str,
        selector_value: str,
        context: str = "",
    ) -> None:
        """
        Record a successful selector for a given site and selector type.

        Args:
            site:           Site identifier (e.g. "linkedin", "naukri")
            selector_type:  Semantic type (e.g. "easy_apply_button", "next_button",
                            "resume_upload", "submit_button")
            selector_value: The exact selector string that worked
            context:        Optional context (e.g. "step_2", "modal_open")
        """
        key = f"{_KEY_SELECTOR}{site}:{selector_type}"
        entry = {
            "selector": selector_value,
            "context": context,
            "timestamp": time.time(),
            "site": site,
        }
        await self._write(key, entry)
        logger.debug(
            "LearningEngine: selector success recorded [%s:%s] = %s",
            site,
            selector_type,
            selector_value,
        )

    async def get_best_selector(self, site: str, selector_type: str) -> str | None:
        """
        Return the most recently successful selector for a given site and type.
        Returns None if no learned selector exists.
        """
        key = f"{_KEY_SELECTOR}{site}:{selector_type}"
        data = await self._read(key)
        if data:
            return data.get("selector")
        return None

    # ── Answer Learning ───────────────────────────────────────────────────────

    async def record_answer(
        self,
        site: str,
        question_normalized: str,
        answer: str,
    ) -> None:
        """
        Record a successful answer for a form question on a specific site.

        Args:
            site:                  Site identifier
            question_normalized:   Lowercase, stripped question text (used as key)
            answer:                The answer that was successfully submitted
        """
        key = f"{_KEY_ANSWER}{site}:{question_normalized[:80]}"
        entry = {
            "answer": answer,
            "question": question_normalized,
            "timestamp": time.time(),
        }
        await self._write(key, entry)
        logger.debug(
            "LearningEngine: answer recorded [%s] '%s' -> '%s'",
            site,
            question_normalized[:40],
            answer[:40],
        )

    async def get_answer(self, site: str, question_normalized: str) -> str | None:
        """
        Return a previously learned answer for a question on a specific site.
        Returns None if no learned answer exists.
        """
        key = f"{_KEY_ANSWER}{site}:{question_normalized[:80]}"
        data = await self._read(key)
        if data:
            return data.get("answer")
        return None

    # ── Failure Recording ─────────────────────────────────────────────────────

    async def record_failure(
        self,
        site: str,
        context: str,
        reason: str,
        selector: str = "",
    ) -> None:
        """
        Record a failed strategy to prevent future re-attempts.

        Args:
            site:     Site identifier
            context:  What was attempted (e.g. "easy_apply_click", "resume_upload")
            reason:   Why it failed
            selector: The selector that failed (if applicable)
        """
        key = f"{_KEY_FAILURE}{site}:{context}:{int(time.time())}"
        entry = {
            "site": site,
            "context": context,
            "reason": reason,
            "selector": selector,
            "timestamp": time.time(),
        }
        await self._write(key, entry)
        logger.debug(
            "LearningEngine: failure recorded [%s] context='%s' reason='%s'",
            site,
            context,
            reason,
        )

    # ── Stats Tracking ────────────────────────────────────────────────────────

    async def increment_stat(self, stat_name: str, amount: int = 1) -> None:
        """
        Increment a named counter in persistent storage.

        Common stats: "total_applications", "successful_submissions",
                      "failed_uploads", "captcha_encounters"
        """
        key = f"{_KEY_STATS}{stat_name}"
        data = await self._read(key) or {"count": 0}
        data["count"] = data.get("count", 0) + amount
        data["last_updated"] = time.time()
        await self._write(key, data)

    async def get_stat(self, stat_name: str) -> int:
        """Return the current value of a named counter."""
        key = f"{_KEY_STATS}{stat_name}"
        data = await self._read(key)
        return data.get("count", 0) if data else 0

    async def get_all_stats(self) -> dict[str, int]:
        """Return all tracked stats as a dict."""
        # This is a lightweight approximation via known stat names
        known = [
            "total_applications",
            "successful_submissions",
            "failed_uploads",
            "captcha_encounters",
            "login_redirects",
            "llm_fallbacks",
            "vision_calls",
        ]
        result = {}
        for name in known:
            result[name] = await self.get_stat(name)
        return result

    # ── Private: DB Helpers ───────────────────────────────────────────────────

    async def _read(self, key: str) -> dict[str, Any] | None:
        try:
            from core.database import get_database

            db = get_database()
            raw = await db.get_memory(key)
            if raw:
                return json.loads(raw)
        except Exception as exc:
            logger.debug("LearningEngine._read error for key=%s: %s", key, exc)
        return None

    async def _write(self, key: str, data: dict[str, Any]) -> None:
        try:
            from core.database import get_database

            db = get_database()
            await db.set_memory(key, json.dumps(data))
        except Exception as exc:
            logger.debug("LearningEngine._write error for key=%s: %s", key, exc)


# ── Singleton ─────────────────────────────────────────────────────────────────

_learning_engine: LearningEngine | None = None


def get_learning_engine() -> LearningEngine:
    """Return the application-wide singleton LearningEngine."""
    global _learning_engine
    if _learning_engine is None:
        _learning_engine = LearningEngine()
    return _learning_engine
