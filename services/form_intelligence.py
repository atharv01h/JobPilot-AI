import re
from collections.abc import Awaitable, Callable
from typing import Any

from core.database import get_database
from core.logger import get_logger
from services.form_service import get_form_service

logger = get_logger(__name__)


class FormIntelligenceEngine:
    def __init__(self) -> None:
        self._memory_cache: dict[str, str] = {}
        self._profile: dict[str, Any] = {}
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return

        # Load structured profile from FormService
        try:
            form_svc = get_form_service()
            if form_svc.is_loaded and form_svc.data:
                self._profile = form_svc.data.__dict__
                logger.info(
                    "FormIntelligenceEngine: Profile loaded with keys: %s",
                    list(self._profile.keys()),
                )
        except Exception as e:
            logger.error("FormIntelligenceEngine: Failed to load profile: %s", e)

        self._initialized = True

    def _normalize_key(self, text: str) -> str:
        # Strip special chars and lowercase
        return re.sub(r"[^a-z0-9]", "", text.lower())

    def _get_canonical_key(self, normalized_label: str) -> str:
        """Map normalized label variations to unified canonical keys to enable high-efficiency caching."""
        if "notice" in normalized_label:
            return "canonical:notice_period"
        if (
            "salary" in normalized_label
            or "ctc" in normalized_label
            or "compensation" in normalized_label
        ):
            return "canonical:expected_salary"
        if "sponsor" in normalized_label or "visa" in normalized_label:
            return "canonical:visa_sponsorship"
        if (
            "authorize" in normalized_label
            or "workin" in normalized_label
            or "legal" in normalized_label
        ):
            return "canonical:work_authorization"
        if "relocate" in normalized_label:
            return "canonical:relocation"
        if "remote" in normalized_label:
            return "canonical:remote"
        if (
            "phone" in normalized_label
            or "mobile" in normalized_label
            or "contact" in normalized_label
        ):
            return "canonical:phone"
        if "cgpa" in normalized_label or "gpa" in normalized_label:
            return "canonical:cgpa"
        if "linkedin" in normalized_label:
            return "canonical:linkedin"
        if "github" in normalized_label:
            return "canonical:github"
        if "portfolio" in normalized_label or "website" in normalized_label:
            return "canonical:portfolio"
        return normalized_label

    async def get_answer(
        self,
        label: str,
        field_type: str,
        llm_fn: Callable[..., Awaitable[str]],
        page: Any | None = None,
        locator: Any | None = None,
        site: str = "generic",
        context_data: dict | None = None,
    ) -> str:
        await self.initialize()

        placeholder = ""
        validation_text = ""
        nearby_text = ""
        if context_data:
            if context_data.get("label"):
                label = context_data["label"]
            placeholder = context_data.get("placeholder", "")
            validation_text = context_data.get("validationText", "")
            nearby_text = context_data.get("nearbyText", "")

        normalized_label = self._normalize_key(label)
        if not normalized_label:
            return ""

        canonical_key = self._get_canonical_key(normalized_label)

        # Source 1: In-memory cache
        if canonical_key in self._memory_cache:
            logger.debug(
                "FormIntelligenceEngine: Cache hit (memory) for '%s' (canonical: '%s')",
                label,
                canonical_key,
            )
            return self._memory_cache[canonical_key]

        # Source 2: SQLite persistent memory / LearningEngine cache
        try:
            from services.learning_engine import get_learning_engine

            le = get_learning_engine()
            cached_ans = await le.get_answer(site, canonical_key)
            if not cached_ans and site != "generic":
                cached_ans = await le.get_answer("generic", canonical_key)
            if cached_ans:
                logger.info(
                    "FormIntelligenceEngine: Cache hit (LearningEngine) for '%s' (canonical: '%s') -> '%s'",
                    label,
                    canonical_key,
                    cached_ans,
                )
                self._memory_cache[canonical_key] = cached_ans
                return cached_ans
        except Exception as e:
            logger.debug("FormIntelligenceEngine: LearningEngine lookup failed: %s", e)

        # Source 3: Profile exact match (deterministic match via profile keywords / FormService)
        ans = self._match_profile_fields(normalized_label)
        if ans:
            logger.info(
                "FormIntelligenceEngine: Profile deterministic match for '%s' -> '%s'",
                label,
                ans,
            )
            await self._cache_and_persist(site, canonical_key, ans)
            self._explain_answer(label, ans, "Profile deterministic match")
            return ans

        # Source 4: ResumeIntelligenceEngine.answer_question()
        try:
            from services.resume_intelligence import get_resume_intelligence

            resume_intel = get_resume_intelligence()
            if not resume_intel.is_ready():
                await resume_intel.initialize()
            if resume_intel.is_ready():
                ctx_str = ""
                if placeholder or validation_text or nearby_text:
                    ctx_str = f"Form Field Context: label='{label}', placeholder='{placeholder}', validation_error='{validation_text}', nearby_content='{nearby_text}'"

                # If field type is unknown or label is missing, try vision reading context
                if (
                    not ctx_str
                    and (field_type == "unknown" or not label)
                    and page is not None
                    and locator is not None
                ):
                    try:
                        from automation.vision_engine import get_vision_engine

                        ve = get_vision_engine()
                        ve_ctx = await ve.read_field_context(page, locator)
                        if ve_ctx:
                            ctx_str = f"Vision context: label={ve_ctx.get('label')}, placeholder={ve_ctx.get('placeholder')}, helper_text={ve_ctx.get('helper_text')}"
                            if ve_ctx.get("label") and not label:
                                label = ve_ctx.get("label")
                                normalized_label = self._normalize_key(label)
                                canonical_key = self._get_canonical_key(
                                    normalized_label
                                )
                    except Exception as ve_err:
                        logger.debug(
                            "FormIntelligenceEngine: Vision context reading failed: %s",
                            ve_err,
                        )

                ans = await resume_intel.answer_question(
                    label, field_type, context=ctx_str
                )
                if ans:
                    logger.info(
                        "FormIntelligenceEngine: ResumeIntelligenceEngine resolved '%s' -> '%s'",
                        label,
                        ans,
                    )
                    await self._cache_and_persist(site, canonical_key, ans)
                    self._explain_answer(
                        label, ans, f"ResumeIntelligenceEngine (context={ctx_str})"
                    )
                    return ans
        except Exception as e:
            logger.warning(
                "FormIntelligenceEngine: ResumeIntelligenceEngine lookup failed: %s", e
            )

        # Source 5: Asynchronous LLM query callback (LLM reasoning fallback)
        logger.info(
            "FormIntelligenceEngine: No cache or deterministic match for '%s'. Querying LLM...",
            label,
        )
        ans = await llm_fn(
            label,
            field_type,
            placeholder=placeholder,
            validation_text=validation_text,
            nearby_text=nearby_text,
        )
        if ans:
            logger.info("FormIntelligenceEngine: LLM resolved '%s' -> '%s'", label, ans)
            await self._cache_and_persist(site, canonical_key, ans)
            self._explain_answer(label, ans, "LLM reasoning callback")
            return ans

        return ""

    async def _cache_and_persist(
        self, site: str, canonical_key: str, value: str
    ) -> None:
        self._memory_cache[canonical_key] = value
        try:
            # Save to general SQLite memory cache
            db = get_database()
            await db.set_memory(canonical_key, value)
            # Save to LearningEngine answer history
            from services.learning_engine import get_learning_engine

            le = get_learning_engine()
            await le.record_answer(site, canonical_key, value)
        except Exception as e:
            logger.debug(
                "FormIntelligenceEngine: Failed to cache and persist '%s': %s",
                canonical_key,
                e,
            )

    def _explain_answer(self, label: str, answer: str, source: str) -> None:
        """Log the reasoning chain for audit trail."""
        logger.info(
            "FormIntelligenceEngine AUDIT: Question: '%s' | Resolved Answer: '%s' | Source: %s",
            label,
            answer,
            source,
        )

    def _get_profile_value(self, pk: str) -> str | None:
        # Support first_name and last_name split
        if pk in ["first_name", "last_name"]:
            # Try to get full_name from self._profile or resume
            full_name = self._profile.get("full_name")
            if not full_name:
                try:
                    from services.resume_intelligence import get_resume_intelligence

                    resume_intel = get_resume_intelligence()
                    if resume_intel.is_ready():
                        rp = resume_intel.get_profile()
                        if rp:
                            full_name = rp.full_name
                except Exception as _exc:
                    logger.debug("Suppressed: %s", _exc)
            if full_name:
                parts = full_name.split()
                if pk == "first_name":
                    return parts[0] if parts else ""
                elif pk == "last_name":
                    return " ".join(parts[1:]) if len(parts) > 1 else ""

        # Try from form.txt profile first
        val = self._profile.get(pk)
        if val:
            return str(val)

        # Try from resume profile next
        try:
            from services.resume_intelligence import get_resume_intelligence

            resume_intel = get_resume_intelligence()
            if resume_intel.is_ready():
                rp = resume_intel.get_profile()
                if rp:
                    # Map pk to ResumeProfile attributes
                    if pk == "full_name":
                        return rp.full_name
                    elif pk == "email":
                        return rp.email
                    elif pk == "mobile" or pk == "whatsapp":
                        return rp.phone
                    elif pk == "current_location" or pk == "hometown":
                        return rp.location
                    elif pk == "linkedin":
                        return rp.linkedin
                    elif pk == "github":
                        return rp.github
                    elif pk == "portfolio":
                        return rp.portfolio
                    elif pk == "total_experience":
                        if rp.experience:
                            return f"{len(rp.experience)} years"
                        return "0 years"
                    elif pk == "notice_period":
                        return "Immediate"
                    elif pk == "highest_qual":
                        if rp.education:
                            return rp.education[0].degree
                    elif pk == "college":
                        if rp.education:
                            return rp.education[0].institution
                    elif pk == "graduation_year":
                        if rp.education:
                            return rp.education[0].year
                    elif pk == "branch":
                        if rp.education:
                            return rp.education[0].branch
                    elif pk == "primary_skills":
                        return ", ".join(rp.skills)
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)
        return None

    def _match_profile_fields(self, normalized_label: str) -> str:
        # Check visa sponsorship / authorization
        if "sponsor" in normalized_label or "visa" in normalized_label:
            val = self._get_profile_value("visa_sponsorship")
            if val:
                return val
            return "No"  # Default conservative answer for visa sponsorship
        if (
            "authorize" in normalized_label
            or "workin" in normalized_label
            or "legal" in normalized_label
        ):
            val = self._get_profile_value("work_authorization")
            if val:
                return val
            return "Yes"

        # Check relocations
        if "relocate" in normalized_label:
            val = self._get_profile_value("willing_relocate")
            if val:
                return val
            return "Yes"
        if "remote" in normalized_label:
            val = self._get_profile_value("willing_remote")
            if val:
                return val
            return "Yes"

        # CGPA / GPA
        if "cgpa" in normalized_label or "gpa" in normalized_label:
            val = self._get_profile_value("cgpa")
            if val:
                return val
            return "8.5"

        # Map labels to profile keys
        mappings = {
            "email": ["email"],
            "phone": ["mobile", "whatsapp"],
            "mobile": ["mobile", "whatsapp"],
            "contact": ["mobile"],
            "fullname": ["full_name"],
            "firstname": ["first_name"],
            "first_name": ["first_name"],
            "lastname": ["last_name"],
            "last_name": ["last_name"],
            "surname": ["last_name"],
            "name": ["full_name"],
            "location": ["current_location"],
            "city": ["current_location"],
            "hometown": ["hometown"],
            "linkedin": ["linkedin"],
            "github": ["github"],
            "portfolio": ["portfolio"],
            "website": ["portfolio", "github"],
            "experience": ["total_experience"],
            "years": ["total_experience"],
            "salary": ["expected_ctc"],
            "ctc": ["expected_ctc"],
            "expected": ["expected_ctc"],
            "notice": ["notice_period"],
            "available": ["available_to_join"],
            "qualify": ["highest_qual"],
            "degree": ["highest_qual"],
            "education": ["highest_qual"],
            "college": ["college"],
            "university": ["college"],
            "school": ["college"],
            "grad": ["graduation_year"],
            "major": ["branch"],
            "branch": ["branch"],
            "skill": ["primary_skills"],
            "gender": ["gender"],
            "nationality": ["nationality"],
            "dob": ["dob"],
        }

        # Check direct mappings
        for keyword, profile_keys in mappings.items():
            if keyword in normalized_label:
                for pk in profile_keys:
                    val = self._get_profile_value(pk)
                    if val:
                        return str(val)

        return ""


_engine_instance: FormIntelligenceEngine | None = None


def get_form_intelligence_engine() -> FormIntelligenceEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = FormIntelligenceEngine()
    return _engine_instance
