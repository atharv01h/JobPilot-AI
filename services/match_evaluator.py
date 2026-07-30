import asyncio
import json
from typing import Any

from core.logger import get_logger
from services.form_service import get_form_service
from services.resume_intelligence import get_resume_intelligence

logger = get_logger(__name__)


async def evaluate_job_match(job_desc: str) -> dict[str, Any]:
    """
    Evaluate job compatibility matching score using NVIDIA NIM.
    Returns:
    {
      "score": int,
      "matching_skills": list[str],
      "missing_skills": list[str],
      "ats_compatibility": str,
      "reason": str
    }
    """
    if not job_desc or not job_desc.strip():
        return {
            "score": 0,
            "matching_skills": [],
            "missing_skills": [],
            "ats_compatibility": "Low",
            "reason": "Empty job description.",
        }

    import hashlib

    from core.database import get_database

    desc_hash = hashlib.md5(job_desc.encode("utf-8")).hexdigest()
    cache_key = f"match_evaluation:{desc_hash}"

    try:
        db = get_database()
        cached_raw = await db.get_memory(cache_key)
        if cached_raw:
            logger.info("evaluate_job_match: Persistent cache hit for job description!")
            return json.loads(cached_raw)
    except Exception as cache_err:
        logger.debug("evaluate_job_match: Cache read failed: %s", cache_err)

    resume_intel = get_resume_intelligence()
    if not resume_intel.is_ready():
        await resume_intel.initialize()

    profile = resume_intel.get_profile()
    profile_ctx = profile.to_context_string() if profile else ""

    fs = get_form_service()
    form_ctx = fs.get_form_summary() if fs.is_loaded else ""

    # Detect if the description is a simple list placeholder
    desc_clean = job_desc.strip()
    is_placeholder = desc_clean.startswith("Job posting for ") and len(desc_clean) < 180

    if is_placeholder:
        # Perform title-based match evaluation
        title_lower = desc_clean.lower()
        skills_matched = []
        # Match primary skills from the profile
        for skill in [
            "java",
            "spring boot",
            "mysql",
            "jdbc",
            "javascript",
            "html",
            "css",
            "rest api",
        ]:
            if skill in title_lower or (profile_ctx and skill in profile_ctx.lower()):
                skills_matched.append(skill.title())

        # EnforceFresher rule: Fresher (0 exp) matches Entry/Associate software roles, but fails Senior/Lead roles
        is_suitable = True
        if any(
            bad in title_lower
            for bad in ["senior", "lead", "architect", "manager", "principal", "sr."]
        ) or not any(
            ok in title_lower
            for ok in [
                "java",
                "software developer",
                "backend",
                "software engineer",
                "spring boot",
                "full stack",
                "programmer",
                "trainee",
                "associate",
            ]
        ):
            is_suitable = False

        score = 85 if is_suitable else 30
        res_data = {
            "score": score,
            "matching_skills": skills_matched,
            "missing_skills": [] if is_suitable else ["Relevant backend title match"],
            "ats_compatibility": "High" if score >= 80 else "Low",
            "reason": "Evaluated based on job title match suitability (placeholder description).",
        }
        try:
            db = get_database()
            await db.set_memory(cache_key, json.dumps(res_data))
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)
        return res_data

    from openai import AsyncOpenAI

    from config.constants import LLM_BASE_URL, LLM_MODEL
    from config.settings import get_settings

    settings = get_settings()
    if not settings.llm_api_key:
        logger.warning(
            "evaluate_job_match: NVIDIA API Key is missing. Returning default score."
        )
        return {
            "score": 85,
            "matching_skills": [],
            "missing_skills": [],
            "ats_compatibility": "Medium",
            "reason": "No NVIDIA API key configured.",
        }

    prompt = (
        "You are an ATS compatibility evaluator.\n\n"
        f"Candidate Resume Details:\n{profile_ctx}\n\n"
        f"Additional Candidate Info:\n{form_ctx}\n\n"
        f"Job Description:\n{job_desc[:4000]}\n\n"
        "Evaluate the compatibility of the candidate's skills and experience against this job description.\n"
        "Generate a score between 0 and 100 representing the match percentage.\n"
        "Return ONLY a valid JSON object matching this structure:\n"
        "{\n"
        '  "score": 90,\n'
        '  "matching_skills": ["Python", "SQL"],\n'
        '  "missing_skills": ["AWS"],\n'
        '  "ats_compatibility": "High",\n'
        '  "reason": "Explain briefly in 1-2 sentences"\n'
        "}\n\n"
        "Return ONLY valid JSON. No explanations, no markdown blocks."
    )

    try:
        client = AsyncOpenAI(base_url=LLM_BASE_URL, api_key=settings.llm_api_key)
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a precise ATS match evaluator. You must return ONLY a raw JSON object and absolutely no other text, markdown blocks, reasoning thoughts, or introductions.",
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=1024,
                temperature=0.1,
            ),
            timeout=20.0,
        )
        content = response.choices[0].message.content.strip()

        # Clean and parse JSON robustly
        import re

        content_clean = content.strip()
        content_clean = re.sub(r"^```(?:json)?\s*", "", content_clean)
        content_clean = re.sub(r"\s*```$", "", content_clean)
        content_clean = content_clean.strip()

        data = None
        try:
            data = json.loads(content_clean)
        except json.JSONDecodeError:
            start_idx = content_clean.find("{")
            end_idx = content_clean.rfind("}")
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                candidate = content_clean[start_idx : end_idx + 1]
                try:
                    data = json.loads(candidate)
                except json.JSONDecodeError:
                    cleaned = re.sub(r",\s*([\]}])", r"\1", candidate)
                    try:
                        data = json.loads(cleaned)
                    except json.JSONDecodeError as err:
                        logger.error(
                            "JSON auto-repair failed: %s (Raw content: %s)",
                            err,
                            content,
                        )
                        raise
            else:
                logger.error("No JSON brackets found in response: %s", content)
                raise

        # Cache the result in DB
        try:
            db = get_database()
            await db.set_memory(cache_key, json.dumps(data))
            logger.info("evaluate_job_match: Match score cached in database.")
        except Exception as cache_err:
            logger.debug("evaluate_job_match: Cache save failed: %s", cache_err)

        logger.info("Job Match Score generated: %d%%", data.get("score", 0))
        return data
    except Exception as e:
        logger.error("evaluate_job_match failed: %s", e)
        return {
            "score": 75,
            "matching_skills": [],
            "missing_skills": [],
            "ats_compatibility": "Medium",
            "reason": f"Evaluation error: {e}",
        }
