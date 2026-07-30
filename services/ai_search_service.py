"""
AI Search Service — expands search keywords using candidate profile, resume, and NVIDIA NIM.
"""

from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from config.constants import LLM_BASE_URL, LLM_MODEL
from config.settings import get_settings
from core.logger import get_logger
from core.service_registry import ServiceRegistry

logger = get_logger(__name__)


class AISearchService:
    """Service to expand search titles based on resume skills and profile."""

    def __init__(self) -> None:
        pass

    async def expand_title(self, base_title: str) -> list[dict[str, Any]]:
        """
        Query NVIDIA NIM to expand base_title into related titles.
        Returns a list of dicts: [{"title": str, "confidence": float}].
        """
        settings = get_settings()
        api_key = settings.llm_api_key
        if not api_key:
            logger.warning(
                "AISearchService: LLM_API_KEY is not set. Using rule-based fallback."
            )
            return self._fallback_expansion(base_title)

        # Retrieve profile details for context
        profile_skills: list[str] = []
        preferred_locs = []
        try:
            profile_service = ServiceRegistry.get("ProfileService")
            if profile_service:
                profile = await profile_service.get_profile()
                if profile:
                    profile_skills = profile.skills or []
                    preferred_locs = (
                        [profile.location] if getattr(profile, "location", None) else []
                    )
        except Exception as e:
            logger.debug("AISearchService: Failed to retrieve profile: %s", e)

        # Build prompt
        prompt = (
            f"You are a recruitment AI agent. The user is searching for jobs with the base title: '{base_title}'.\n"
            f"Candidate Skills: {', '.join(profile_skills) or 'Not specified'}\n"
            f"Preferred Locations: {', '.join(preferred_locs) or 'Not specified'}\n\n"
            "Generate a list of 20 to 100 closely related job search titles suitable for this candidate. "
            "For each title, assign a confidence score between 0.0 and 1.0 (indicating suitability for search expansion).\n\n"
            "Output must be a valid JSON object matching this schema exactly. Do not wrap in markdown code blocks:\n"
            "{\n"
            '  "expansions": [\n'
            '    {"title": "Full Stack Engineer", "confidence": 0.95},\n'
            '    {"title": "Python Developer", "confidence": 0.85}\n'
            "  ]\n"
            "}"
        )

        try:
            client = AsyncOpenAI(base_url=LLM_BASE_URL, api_key=api_key)
            response = await client.chat.completions.create(
                model=LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or ""
            data = json.loads(content)
            expansions = data.get("expansions", [])
            if expansions:
                # Sort descending by confidence
                expansions.sort(key=lambda x: x.get("confidence", 0.0), reverse=True)
                return expansions
        except Exception as e:
            logger.error(
                "AISearchService: NIM keyword expansion failed: %s. Using fallback.", e
            )

        return self._fallback_expansion(base_title)

    def _fallback_expansion(self, base_title: str) -> list[dict[str, Any]]:
        """Fallback expansion list when NIM is unavailable."""
        title_clean = base_title.lower()

        # Standard software engineer rules
        if (
            "software" in title_clean
            or "engineer" in title_clean
            or "developer" in title_clean
        ):
            return [
                {"title": base_title, "confidence": 1.0},
                {"title": "Software Developer", "confidence": 0.95},
                {"title": "Software Engineer", "confidence": 0.95},
                {"title": "Backend Developer", "confidence": 0.90},
                {"title": "Backend Engineer", "confidence": 0.90},
                {"title": "Full Stack Developer", "confidence": 0.90},
                {"title": "Full Stack Engineer", "confidence": 0.90},
                {"title": "Application Developer", "confidence": 0.85},
                {"title": "Platform Engineer", "confidence": 0.85},
                {"title": "Systems Engineer", "confidence": 0.80},
                {"title": "Cloud Engineer", "confidence": 0.80},
                {"title": "Graduate Software Engineer", "confidence": 0.80},
                {"title": "Associate Software Engineer", "confidence": 0.80},
                {"title": "Entry Level Developer", "confidence": 0.75},
                {"title": "SDE", "confidence": 0.75},
                {"title": "Java Developer", "confidence": 0.75},
                {"title": "Python Developer", "confidence": 0.75},
                {"title": "React Developer", "confidence": 0.70},
                {"title": "Node Developer", "confidence": 0.70},
                {"title": "Web Developer", "confidence": 0.70},
                {"title": "Technical Engineer", "confidence": 0.65},
                {"title": "Technology Analyst", "confidence": 0.65},
                {"title": "DevOps Engineer", "confidence": 0.60},
                {"title": "Site Reliability Engineer", "confidence": 0.60},
                {"title": "Frontend Developer", "confidence": 0.60},
                {"title": "Frontend Engineer", "confidence": 0.60},
                {"title": "UI Engineer", "confidence": 0.55},
                {"title": "API Developer", "confidence": 0.55},
                {"title": "SDE I", "confidence": 0.50},
                {"title": "SDE II", "confidence": 0.50},
            ]

        # Standard fallback if unrecognized
        return [
            {"title": base_title, "confidence": 1.0},
            {"title": f"Junior {base_title}", "confidence": 0.90},
            {"title": f"Associate {base_title}", "confidence": 0.90},
            {"title": f"Trainee {base_title}", "confidence": 0.80},
            {"title": f"Assistant {base_title}", "confidence": 0.70},
            {"title": f"Senior {base_title}", "confidence": 0.60},
            {"title": f"Lead {base_title}", "confidence": 0.50},
        ]


# Singleton
_ai_search_service: AISearchService | None = None


def get_ai_search_service() -> AISearchService:
    global _ai_search_service
    if _ai_search_service is None:
        _ai_search_service = AISearchService()
        try:
            ServiceRegistry.register("AISearchService", _ai_search_service)
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)
    return _ai_search_service
