"""
resume_intelligence.py — V9 Resume Intelligence Engine.

Parses the resume PDF once at startup into a structured ResumeProfile using
PyMuPDF + NVIDIA NIM structured extraction. The profile is cached in the
knowledge_memory SQLite table so re-parsing is skipped across restarts.

The engine answers any form question from resume knowledge before going to
the general LLM — this reduces tokens, improves accuracy, and eliminates
hallucinated answers for personal data fields.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from core.logger import get_logger

logger = get_logger(__name__)

_CACHE_KEY = "resume_intelligence:profile_v1"


# ── Data Model ────────────────────────────────────────────────────────────────


@dataclass
class EducationEntry:
    degree: str = ""
    institution: str = ""
    year: str = ""
    gpa: str = ""
    branch: str = ""


@dataclass
class ExperienceEntry:
    title: str = ""
    company: str = ""
    duration: str = ""
    description: str = ""


@dataclass
class ProjectEntry:
    name: str = ""
    tech: str = ""
    description: str = ""
    url: str = ""


@dataclass
class ResumeProfile:
    """Structured representation of a candidate's resume."""

    full_name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin: str = ""
    github: str = ""
    portfolio: str = ""
    summary: str = ""
    skills: list[str] = field(default_factory=list)
    education: list[EducationEntry] = field(default_factory=list)
    experience: list[ExperienceEntry] = field(default_factory=list)
    projects: list[ProjectEntry] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    achievements: list[str] = field(default_factory=list)
    raw_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict (JSON-safe)."""
        d = asdict(self)
        d["education"] = [asdict(e) for e in self.education]
        d["experience"] = [asdict(e) for e in self.experience]
        d["projects"] = [asdict(e) for e in self.projects]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ResumeProfile:
        """Deserialize from a plain dict."""
        p = cls()
        for k, v in d.items():
            if k == "education":
                p.education = [EducationEntry(**e) for e in (v or [])]
            elif k == "experience":
                p.experience = [ExperienceEntry(**e) for e in (v or [])]
            elif k == "projects":
                p.projects = [ProjectEntry(**e) for e in (v or [])]
            elif hasattr(p, k):
                setattr(p, k, v)
        return p

    def to_context_string(self) -> str:
        """Return a concise text summary suitable for LLM context injection."""
        edu_str = "; ".join(
            f"{e.degree} in {e.branch} from {e.institution} ({e.year})"
            for e in self.education
        )
        exp_str = "; ".join(
            f"{e.title} at {e.company} ({e.duration})" for e in self.experience
        )
        proj_str = "; ".join(f"{p.name} ({p.tech})" for p in self.projects)
        return (
            f"Name: {self.full_name}\n"
            f"Email: {self.email}\n"
            f"Phone: {self.phone}\n"
            f"Location: {self.location}\n"
            f"LinkedIn: {self.linkedin}\n"
            f"GitHub: {self.github}\n"
            f"Skills: {', '.join(self.skills)}\n"
            f"Education: {edu_str}\n"
            f"Experience: {exp_str}\n"
            f"Projects: {proj_str}\n"
            f"Certifications: {', '.join(self.certifications)}\n"
            f"Summary: {self.summary}"
        )


# ── Resume Intelligence Engine ────────────────────────────────────────────────


class ResumeIntelligenceEngine:
    """
    Extracts a structured profile from a PDF resume and answers form questions
    using resume knowledge, FormService data, and optionally the LLM.
    """

    def __init__(self) -> None:
        self._profile: ResumeProfile | None = None
        self._parsed = False

    # ── Initialization ────────────────────────────────────────────────────────

    async def initialize(self) -> bool:
        """
        Load and parse the resume. Checks the knowledge_memory cache first.
        Returns True if a valid profile is available.
        """
        # 1. Try loading from SQLite cache
        cached = await self._load_from_cache()
        if cached:
            self._profile = cached
            self._parsed = True
            logger.info("ResumeIntelligenceEngine: profile loaded from cache.")
            return True

        # 2. Parse the PDF
        try:
            raw_text = self._extract_pdf_text()
            if not raw_text.strip():
                logger.error(
                    "ResumeIntelligenceEngine: PDF text extraction returned empty."
                )
                return False

            profile = await self._extract_profile_with_llm(raw_text)
            if profile:
                profile.raw_text = raw_text
                self._profile = profile
                self._parsed = True
                await self._save_to_cache(profile)
                logger.info("ResumeIntelligenceEngine: profile parsed and cached.")
                return True
        except Exception as exc:
            logger.error("ResumeIntelligenceEngine: initialization failed: %s", exc)
        return False

    # ── Public API ────────────────────────────────────────────────────────────

    def get_profile(self) -> ResumeProfile | None:
        """Return the parsed ResumeProfile or None if not yet initialized."""
        return self._profile

    def is_ready(self) -> bool:
        return self._parsed and self._profile is not None

    async def answer_question(
        self,
        question: str,
        field_type: str = "text",
        context: str = "",
    ) -> str:
        """
        Generate the best possible answer to a form question.

        Answer source priority:
          1. Deterministic lookup from ResumeProfile fields (no LLM needed)
          2. FormService data (form.txt — highest priority for personal data)
          3. LLM reasoning using profile + form context
        """
        # 1. Try form.txt first (user-specified data takes absolute priority)
        form_answer = self._lookup_form_service(question, field_type)
        if form_answer:
            return form_answer

        # 2. Try direct profile field match
        if self._profile:
            profile_answer = self._lookup_profile(question, field_type)
            if profile_answer:
                return profile_answer

        # 3. Fall back to LLM reasoning
        return await self._llm_answer(question, field_type, context)

    async def generate_cover_letter(self, job_title: str, company: str) -> str:
        """Generate a tailored ~150-word cover letter using resume profile."""
        if not self._profile:
            return ""

        from openai import AsyncOpenAI  # type: ignore

        from config.constants import LLM_BASE_URL, LLM_MODEL
        from config.settings import get_settings

        settings = get_settings()
        client = AsyncOpenAI(base_url=LLM_BASE_URL, api_key=settings.llm_api_key)

        profile_ctx = self._profile.to_context_string()
        prompt = (
            f"Write a professional, concise cover letter (exactly 120-150 words) for:\n"
            f"Job Title: {job_title}\n"
            f"Company: {company}\n\n"
            f"Candidate Profile:\n{profile_ctx}\n\n"
            "Instructions:\n"
            "- Be specific about skills that match the role\n"
            "- Show genuine enthusiasm\n"
            "- Use formal but warm tone\n"
            "- End with a clear call to action\n"
            "- Return only the cover letter text, no subject line, no placeholders"
        )

        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=LLM_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=300,
                    temperature=0.4,
                ),
                timeout=20.0,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            logger.error(
                "ResumeIntelligenceEngine: cover letter generation failed: %s", exc
            )
            return ""

    # ── Private: PDF Extraction ───────────────────────────────────────────────

    def _extract_pdf_text(self) -> str:
        """Extract raw text from the resume PDF using PyMuPDF."""
        import fitz  # PyMuPDF

        from config.settings import get_settings

        settings = get_settings()
        resume_path = settings.resume_path

        doc = fitz.open(resume_path)
        pages_text = []
        for page in doc:
            pages_text.append(page.get_text("text"))
        doc.close()

        raw = "\n".join(pages_text)
        logger.info(
            "ResumeIntelligenceEngine: extracted %d chars from PDF (%d pages).",
            len(raw),
            len(pages_text),
        )
        return raw

    # ── Private: LLM Extraction ───────────────────────────────────────────────

    async def _extract_profile_with_llm(self, raw_text: str) -> ResumeProfile | None:
        """
        Use NVIDIA NIM to extract a structured JSON profile from raw PDF text.
        """
        from openai import AsyncOpenAI  # type: ignore

        from config.constants import LLM_BASE_URL, LLM_MODEL
        from config.settings import get_settings

        settings = get_settings()
        client = AsyncOpenAI(base_url=LLM_BASE_URL, api_key=settings.llm_api_key)

        schema_desc = (
            "Extract a structured profile from this resume text. "
            "Return ONLY valid JSON matching this exact structure:\n"
            "{\n"
            '  "full_name": "",\n'
            '  "email": "",\n'
            '  "phone": "",\n'
            '  "location": "",\n'
            '  "linkedin": "",\n'
            '  "github": "",\n'
            '  "portfolio": "",\n'
            '  "summary": "",\n'
            '  "skills": ["skill1", "skill2"],\n'
            '  "education": [{"degree": "", "institution": "", "year": "", "gpa": "", "branch": ""}],\n'
            '  "experience": [{"title": "", "company": "", "duration": "", "description": ""}],\n'
            '  "projects": [{"name": "", "tech": "", "description": "", "url": ""}],\n'
            '  "certifications": ["cert1"],\n'
            '  "languages": ["English"],\n'
            '  "achievements": ["ach1"]\n'
            "}\n\n"
            f"Resume Text:\n{raw_text[:6000]}"  # Limit to 6000 chars
        )

        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=LLM_MODEL,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are a resume parsing AI. Extract structured data precisely. "
                                "Return only valid JSON, no markdown, no explanation."
                            ),
                        },
                        {"role": "user", "content": schema_desc},
                    ],
                    max_tokens=2048,
                    temperature=0.1,
                ),
                timeout=30.0,
            )
            content = response.choices[0].message.content.strip()
            # Strip markdown code blocks if present
            content = re.sub(r"```(?:json)?\n?", "", content).strip().rstrip("`")
            data = json.loads(content)
            return ResumeProfile.from_dict(data)
        except json.JSONDecodeError as exc:
            logger.error("ResumeIntelligenceEngine: JSON parse error from LLM: %s", exc)
        except asyncio.TimeoutError:
            logger.error("ResumeIntelligenceEngine: LLM extraction timed out.")
        except Exception as exc:
            logger.error("ResumeIntelligenceEngine: LLM extraction failed: %s", exc)
        return None

    # ── Private: Answer Lookup ────────────────────────────────────────────────

    def _lookup_profile(self, question: str, field_type: str) -> str:
        """Try to answer a form question using the parsed ResumeProfile fields."""
        if not self._profile:
            return ""

        q = question.lower().strip()
        p = self._profile

        # Direct field mapping rules
        rules = [
            (
                ["full name", "your name", "first name", "last name", "name"],
                p.full_name,
            ),
            (["email", "e-mail", "email address"], p.email),
            (["phone", "mobile", "contact number", "telephone"], p.phone),
            (["location", "city", "current city", "where are you based"], p.location),
            (["linkedin", "linkedin profile", "linkedin url"], p.linkedin),
            (["github", "github profile", "github url"], p.github),
            (["portfolio", "website", "personal website"], p.portfolio),
            (
                ["summary", "about yourself", "brief introduction", "objective"],
                p.summary,
            ),
            (
                ["skills", "technical skills", "key skills", "programming languages"],
                ", ".join(p.skills),
            ),
            (["certifications", "certificates"], ", ".join(p.certifications)),
        ]

        for keywords, value in rules:
            if any(kw in q for kw in keywords) and value:
                return str(value)

        # Education answers
        if p.education:
            edu = p.education[0]
            if any(kw in q for kw in ["degree", "qualification", "highest education"]):
                return edu.degree
            if any(
                kw in q for kw in ["university", "college", "institution", "school"]
            ):
                return edu.institution
            if any(kw in q for kw in ["graduation year", "year of passing", "batch"]):
                return edu.year
            if any(
                kw in q
                for kw in ["branch", "major", "specialization", "field of study"]
            ):
                return edu.branch
            if any(kw in q for kw in ["gpa", "cgpa", "percentage", "marks"]):
                return edu.gpa

        # Experience answers
        if p.experience:
            exp = p.experience[0]
            if any(kw in q for kw in ["current company", "employer", "organization"]):
                return exp.company
            if any(
                kw in q
                for kw in ["current role", "designation", "job title", "position"]
            ):
                return exp.title

        return ""

    def _lookup_form_service(self, question: str, field_type: str) -> str:
        """Check form.txt (FormService) for the answer — highest priority data source."""
        try:
            from services.form_service import get_form_service

            fs = get_form_service()
            if fs.is_loaded:
                return fs.get_field(question) or ""
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)
        return ""

    async def _llm_answer(self, question: str, field_type: str, context: str) -> str:
        """Use the LLM to answer a form question using resume + form context."""
        from openai import AsyncOpenAI  # type: ignore

        from config.constants import LLM_BASE_URL, LLM_MODEL
        from config.settings import get_settings

        settings = get_settings()
        if not settings.llm_api_key:
            return ""

        profile_ctx = self._profile.to_context_string() if self._profile else ""
        form_ctx = self._get_form_summary()

        prompt = (
            f"You are filling out a job application form.\n\n"
            f"Candidate Profile:\n{profile_ctx}\n\n"
            f"Additional Form Data:\n{form_ctx}\n\n"
            f"Page Context: {context}\n\n"
            f"Form Question: {question}\n"
            f"Field Type: {field_type}\n\n"
            "Provide the best answer for this form field. "
            "Return ONLY the answer value, no explanation, no quotes."
        )

        try:
            client = AsyncOpenAI(base_url=LLM_BASE_URL, api_key=settings.llm_api_key)
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=LLM_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=150,
                    temperature=0.2,
                ),
                timeout=15.0,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            logger.error("ResumeIntelligenceEngine._llm_answer failed: %s", exc)
            return ""

    def _get_form_summary(self) -> str:
        """Get a brief summary from FormService for LLM context."""
        try:
            from services.form_service import get_form_service

            fs = get_form_service()
            if fs.is_loaded:
                return fs.get_form_summary()
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)
        return ""

    def _get_cache_key(self) -> str:
        """Generate a cache key based on the modification time and size of the resume PDF."""
        from pathlib import Path

        from config.settings import get_settings

        try:
            settings = get_settings()
            path = Path(settings.resume_path)
            if path.exists():
                mtime = path.stat().st_mtime
                size = path.stat().st_size
                return f"resume_intelligence:profile_v2:{mtime}:{size}"
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)
        return "resume_intelligence:profile_v2:default"

    async def _load_from_cache(self) -> ResumeProfile | None:
        """Load the profile from knowledge_memory table if available."""
        try:
            from core.database import get_database

            db = get_database()
            cache_key = self._get_cache_key()
            raw = await db.get_memory(cache_key)
            if raw:
                data = json.loads(raw)
                profile = ResumeProfile.from_dict(data)
                if profile.full_name:  # Validate it's a real profile
                    return profile
        except Exception as exc:
            logger.debug("ResumeIntelligenceEngine: cache load error: %s", exc)
        return None

    async def _save_to_cache(self, profile: ResumeProfile) -> None:
        """Persist the profile to knowledge_memory table."""
        try:
            from core.database import get_database

            db = get_database()
            cache_key = self._get_cache_key()
            await db.set_memory(cache_key, json.dumps(profile.to_dict()))
            logger.info("ResumeIntelligenceEngine: profile saved to cache.")
        except Exception as exc:
            logger.warning("ResumeIntelligenceEngine: cache save error: %s", exc)


# ── Singleton ─────────────────────────────────────────────────────────────────

_engine: ResumeIntelligenceEngine | None = None


def get_resume_intelligence() -> ResumeIntelligenceEngine:
    """Return the application-wide singleton ResumeIntelligenceEngine."""
    global _engine
    if _engine is None:
        _engine = ResumeIntelligenceEngine()
    return _engine
