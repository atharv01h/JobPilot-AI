"""
Application-wide constants: keywords, locations, sources, experience levels,
color palette, UI tokens, and production infrastructure settings.
"""

import re

# ─── Job Search Constants ──────────────────────────────────────────────────────

SEARCH_KEYWORDS: list[str] = [
    "Software Engineer",
    "Software Developer",
    "Backend Developer",
    "Java Developer",
    "Python Developer",
    "Full Stack Developer",
    "Spring Boot Developer",
    "Associate Software Engineer",
    "Graduate Engineer Trainee",
]

SEARCH_LOCATIONS: list[str] = [
    "Pune",
    "Mumbai",
    "Bengaluru",
    "Hyderabad",
    "Remote",
]

EXPERIENCE_LEVELS: list[str] = [
    "Fresher",
    "Entry Level",
    "0-1 Years",
    "0-2 Years",
]

JOB_SOURCES: list[str] = [
    "LinkedIn",
    "Naukri",
    "Indeed",
    "Glassdoor",
    "Foundit",
]

JOB_SOURCE_URLS: dict = {
    "LinkedIn": "https://www.linkedin.com/jobs/search/",
    "Naukri": "https://www.naukri.com/",
    "Indeed": "https://in.indeed.com/",
    "Glassdoor": "https://www.glassdoor.co.in/Job/index.htm",
    "Foundit": "https://www.foundit.in/",
}

# ─── Experience Filter ─────────────────────────────────────────────────────────

MAX_EXPERIENCE_YEARS: int = 2  # Skip jobs requiring > 2 years
FRESHER_KEYWORDS: list[str] = [
    "fresher",
    "fresh graduate",
    "entry level",
    "0 years",
    "0-1",
    "0-2",
    "trainee",
    "associate",
    "junior",
    "graduate engineer",
    "freshers eligible",
    "0 to 1",
    "0 to 2",
]


def is_experience_suitable(exp_text: str) -> bool:
    """Return True if job is suitable for a fresher (0-2 yrs experience)."""
    if not exp_text:
        return True
    text = exp_text.lower()

    # 1. Check for explicit fresher keywords
    for kw in FRESHER_KEYWORDS:
        pattern = r"(?<!\d)" + re.escape(kw) + r"(?!\d)"
        if re.search(pattern, text):
            return True

    # 2. Check if the text actually refers to experience.
    # If it doesn't mention "year", "yr", "exp", "fresher", or "experience", it might be unrelated text.
    # In that case, we shouldn't reject the job.
    exp_indicators = ["year", "yr", "exp", "fresher", "experience"]
    if not any(ind in text for ind in exp_indicators):
        return True

    # 3. Extract numbers associated with experience/years
    # Matches patterns like "0-3 years", "1 to 2 yrs", "0 to 2 years", "5+ years", etc.
    matches = re.findall(
        r"(\d+)\s*(?:-|to)?\s*(\d+)?\s*(?:year|yr|y|annum|exp|experience)", text
    )
    if matches:
        for min_str, max_str in matches:
            min_val = int(min_str)
            if min_val <= MAX_EXPERIENCE_YEARS:
                return True
        return False

    # 4. Fallback: extract numbers between 0 and 15 (potential experience years)
    # and verify if the minimum required experience is <= MAX_EXPERIENCE_YEARS.
    numbers = [int(n) for n in re.findall(r"\d+", text)]
    experience_numbers = [n for n in numbers if 0 <= n <= 15]
    if experience_numbers:
        return min(experience_numbers) <= MAX_EXPERIENCE_YEARS

    return True


# ─── Scheduler Options ────────────────────────────────────────────────────────

SCHEDULER_OPTIONS: list[str] = ["Manual", "Every Hour", "Daily", "Weekly"]

# ─── GUI Color Palette (Dark Theme) ───────────────────────────────────────────

COLORS = {
    # Backgrounds
    "bg_primary": "#0D0F14",
    "bg_secondary": "#13161E",
    "bg_card": "#1A1E2A",
    "bg_sidebar": "#10131A",
    "bg_hover": "#22273A",
    # Accents
    "accent_primary": "#6C63FF",
    "accent_secondary": "#A78BFA",
    "accent_green": "#22C55E",
    "accent_red": "#EF4444",
    "accent_orange": "#F59E0B",
    "accent_cyan": "#06B6D4",
    # Text
    "text_primary": "#F1F5F9",
    "text_secondary": "#94A3B8",
    "text_muted": "#475569",
    # Borders
    "border": "#2D3450",
    "border_active": "#6C63FF",
    # Status colours
    "status_new": "#6C63FF",
    "status_saved": "#06B6D4",
    "status_applied": "#22C55E",
    "status_error": "#EF4444",
}

# ─── Font Configuration ───────────────────────────────────────────────────────

FONTS = {
    "heading_xl": ("Inter", 28, "bold"),
    "heading_lg": ("Inter", 22, "bold"),
    "heading_md": ("Inter", 18, "bold"),
    "heading_sm": ("Inter", 14, "bold"),
    "body_lg": ("Inter", 14, "normal"),
    "body_md": ("Inter", 12, "normal"),
    "body_sm": ("Inter", 11, "normal"),
    "mono": ("Consolas", 11, "normal"),
    "label": ("Inter", 11, "bold"),
}

# ─── Window Dimensions ────────────────────────────────────────────────────────

WINDOW_MIN_WIDTH = 1280
WINDOW_MIN_HEIGHT = 800
SIDEBAR_WIDTH = 220

# ─── Database Tables ──────────────────────────────────────────────────────────

DB_TABLES = [
    "jobs",
    "saved_jobs",
    "applied_jobs",
    "notifications",
    "search_history",
    "errors",
]

# ─── Log Configuration ────────────────────────────────────────────────────────

LOG_FILE = "logs/job_assistant.log"
LOG_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
LOG_BACKUP_COUNT = 3

# ─── Browser-Use Settings ─────────────────────────────────────────────────────

BROWSER_USE_VISION = False  # NEVER enable vision mode
BROWSER_TIMEOUT = 600  # seconds per browser task (10 min for ATS workflows)
MAX_RETRIES = 2  # max agent retries (keep low to avoid redundant browser launches)

# ─── NVIDIA NIM ───────────────────────────────────────────────────────────────

LLM_BASE_URL = "https://integrate.api.nvidia.com/v1"
LLM_MODEL = "nvidia/nemotron-3-super-120b-a12b"

# ─── Browser / CDP Infrastructure ─────────────────────────────────────────────

# Brave browser executable — only one location to change if path differs
BRAVE_EXE_PATH = "C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe"

# Remote debugging port Brave is launched on
CDP_PORT = 9223

# Timeouts for CDP operations (seconds)
CDP_TIMEOUT_CONNECT = 15.0  # connect_over_cdp()
CDP_TIMEOUT_PAGE = 10.0  # new_page() or context enumeration
CDP_TIMEOUT_HTTP = 2.0  # /json/version HTTP probe
CDP_TIMEOUT_NAV = 25.0  # page.goto() during scraping
CDP_TIMEOUT_SELECTOR = 12.0  # wait_for_selector() during scraping

# Retry / backoff
CDP_MAX_LAUNCH_ATTEMPTS = 2  # How many times to kill+relaunch Brave before giving up
CDP_LAUNCH_POLL_INTERVAL = 0.5  # seconds between port-open checks after launch
CDP_LAUNCH_POLL_ATTEMPTS = (
    20  # max polls before declaring launch failed (20 × 0.5s = 10s)
)

# ─── Scraper Concurrency ──────────────────────────────────────────────────────

SCRAPER_CONCURRENCY = 3  # Max parallel scraper tasks
TARGET_JOBS_PER_SEARCH = 20  # Stop searching once this many unique new jobs are found

# ─── Watchdog / Health Monitor ────────────────────────────────────────────────

WATCHDOG_INACTIVITY_S = 30  # Seconds of silence before watchdog triggers
BROWSER_HEALTH_PING_S = 30  # CDP health-check ping interval
BROWSER_HEALTH_MAX_FAILURES = 3  # Consecutive failures before declaring browser dead

# ─── Vision AI (V9) ───────────────────────────────────────────────────────────

# Meta Llama 3.2 11B Vision via NVIDIA NIM — same base_url, same API key as reasoning model
VISION_MODEL = "meta/llama-3.2-11b-vision-instruct"
VISION_TIMEOUT = 25.0  # seconds per vision call

# ─── Learning Engine (V9) ─────────────────────────────────────────────────────

LEARNING_ENGINE_ENABLED = True  # Persist successful selectors/answers to SQLite

# ─── Scraper Settings (V9) ───────────────────────────────────────────────────

# Scraper uses its own isolated headless Chromium — NEVER the shared Brave pool
SCRAPER_HEADLESS = True
SCRAPER_CONTEXT_TIMEOUT = 30000  # ms — page.goto() timeout for scrapers
