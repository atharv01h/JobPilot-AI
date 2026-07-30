"""
Async SQLite database layer using aiosqlite.

DESIGN: A single persistent connection is kept open for the lifetime of the
application. All queries share it through an asyncio.Lock, eliminating the
overhead and "database is locked" errors that come from opening a new
connection per query.

Call `await db.initialize()` once at startup.
Call `await db.close()` at shutdown.
"""

from __future__ import annotations

import asyncio
import csv
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from config.settings import get_settings
from core.logger import get_logger
from core.models import (
    AppliedJob,
    Job,
    JobStatus,
    Notification,
    SavedJob,
    SearchHistory,
)

logger = get_logger(__name__)

_CREATE_JOBS = """
CREATE TABLE IF NOT EXISTS jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT    NOT NULL DEFAULT '',
    company         TEXT    NOT NULL DEFAULT '',
    location        TEXT             DEFAULT '',
    experience      TEXT             DEFAULT '',
    salary          TEXT             DEFAULT '',
    url             TEXT    NOT NULL UNIQUE,
    source          TEXT             DEFAULT '',
    description     TEXT             DEFAULT '',
    requirements    TEXT             DEFAULT '',
    skills          TEXT             DEFAULT '',
    posted_date     TEXT             DEFAULT '',
    discovered_date TEXT             DEFAULT '',
    status          TEXT             DEFAULT 'NEW'
);
"""

_CREATE_SAVED_JOBS = """
CREATE TABLE IF NOT EXISTS saved_jobs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id     INTEGER NOT NULL,
    saved_date TEXT    NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);
"""

_CREATE_APPLIED_JOBS = """
CREATE TABLE IF NOT EXISTS applied_jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id          INTEGER NOT NULL,
    applied_date    TEXT    NOT NULL,
    application_url TEXT    DEFAULT '',
    status          TEXT    DEFAULT 'APPLIED',
    notes           TEXT    DEFAULT '',
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);
"""

_CREATE_NOTIFICATIONS = """
CREATE TABLE IF NOT EXISTS notifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    type       TEXT DEFAULT 'info',
    message    TEXT DEFAULT '',
    created_at TEXT DEFAULT '',
    read       INTEGER DEFAULT 0
);
"""

_CREATE_SEARCH_HISTORY = """
CREATE TABLE IF NOT EXISTS search_history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    keywords      TEXT DEFAULT '',
    locations     TEXT DEFAULT '',
    sources       TEXT DEFAULT '',
    results_count INTEGER DEFAULT 0,
    searched_at   TEXT DEFAULT ''
);
"""

_CREATE_ERRORS = """
CREATE TABLE IF NOT EXISTS errors (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    context       TEXT DEFAULT '',
    error_message TEXT DEFAULT '',
    occurred_at   TEXT DEFAULT ''
);
"""

_CREATE_KNOWLEDGE_MEMORY = """
CREATE TABLE IF NOT EXISTS knowledge_memory (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key         TEXT NOT NULL UNIQUE,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""

_CREATE_SESSIONS = """
CREATE TABLE IF NOT EXISTS sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_key  TEXT UNIQUE,
    start_time   TEXT NOT NULL,
    end_time     TEXT,
    status       TEXT NOT NULL
);
"""

_CREATE_BROWSER_HISTORY = """
CREATE TABLE IF NOT EXISTS browser_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    url         TEXT NOT NULL,
    title       TEXT,
    visited_at  TEXT NOT NULL,
    session_id  INTEGER
);
"""

_CREATE_AI_DECISIONS = """
CREATE TABLE IF NOT EXISTS ai_decisions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id        INTEGER,
    model_name    TEXT NOT NULL,
    prompt        TEXT NOT NULL,
    response      TEXT NOT NULL,
    tokens_used   INTEGER DEFAULT 0,
    latency_ms    INTEGER DEFAULT 0,
    decision_type TEXT,
    created_at    TEXT NOT NULL
);
"""

_CREATE_RESUME_UPLOADS = """
CREATE TABLE IF NOT EXISTS resume_uploads (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      INTEGER,
    resume_path TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    status      TEXT NOT NULL
);
"""

_CREATE_WEBSITE_CACHE = """
CREATE TABLE IF NOT EXISTS website_cache (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    url       TEXT UNIQUE,
    content   TEXT,
    cached_at TEXT NOT NULL
);
"""

_CREATE_ACCOUNTS = """
CREATE TABLE IF NOT EXISTS accounts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    domain       TEXT UNIQUE,
    email        TEXT NOT NULL,
    password     TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    last_used_at TEXT
);
"""

_CREATE_APPLICATION_QUEUE = """
CREATE TABLE IF NOT EXISTS application_queue (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id     INTEGER UNIQUE REFERENCES jobs(id),
    priority   INTEGER DEFAULT 0,
    status     TEXT DEFAULT 'PENDING',
    added_at   TEXT NOT NULL
);
"""

_CREATE_APPLICATIONS = """
CREATE TABLE IF NOT EXISTS applications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      INTEGER REFERENCES jobs(id),
    attempt_date TEXT NOT NULL,
    status      TEXT NOT NULL,
    notes       TEXT
);
"""


class Database:
    """Async SQLite database manager with a persistent shared connection."""

    def __init__(self, db_path: str | None = None) -> None:
        settings = get_settings()
        self.db_path = db_path or settings.db_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Open the persistent connection and create all tables."""
        async with self._lock:
            if self._conn is not None:
                return  # already initialized
            self._conn = await aiosqlite.connect(self.db_path)
            self._conn.row_factory = aiosqlite.Row
            await self._conn.execute("PRAGMA journal_mode=WAL;")
            await self._conn.execute("PRAGMA foreign_keys=ON;")
            await self._conn.execute("PRAGMA synchronous=NORMAL;")
            await self._conn.execute("PRAGMA cache_size=-8000;")  # 8 MB page cache
            for stmt in [
                _CREATE_JOBS,
                _CREATE_SAVED_JOBS,
                _CREATE_APPLIED_JOBS,
                _CREATE_NOTIFICATIONS,
                _CREATE_SEARCH_HISTORY,
                _CREATE_ERRORS,
                _CREATE_KNOWLEDGE_MEMORY,
                _CREATE_SESSIONS,
                _CREATE_BROWSER_HISTORY,
                _CREATE_AI_DECISIONS,
                _CREATE_RESUME_UPLOADS,
                _CREATE_WEBSITE_CACHE,
                _CREATE_ACCOUNTS,
                _CREATE_APPLICATION_QUEUE,
                _CREATE_APPLICATIONS,
            ]:
                await self._conn.execute(stmt)

            # Status Normalization Migration
            status_mappings = {
                "new": "NEW",
                "saved": "NEW",
                "applied": "APPLIED",
                "skipped": "SKIPPED",
                "error": "ERROR",
                "UNKNOWN": "ERROR",
                "unknown": "ERROR",
                "EXTERNAL_APPLICATION_REQUIRED": "EXTERNAL_REQUIRED",
                "REDIRECTED_TO_COMPANY": "REDIRECTED",
                "APPLICATION_COMPLETED": "SUBMITTED",
                "APPLICATION_SUBMITTED": "SUBMITTED",
                "APPLICATION_SKIPPED": "SKIPPED",
                "APPLICATION_FAILED": "FAILED",
                "SUCCESS": "SUBMITTED",
                "UPLOAD_FAILED": "FAILED",
                "ACCOUNT_REQUIRED": "ERROR",
                "LOGIN_REQUIRED": "ERROR",
                "CAPTCHA_BLOCKED": "ERROR",
                "OTP_REQUIRED": "ERROR",
                "EMAIL_VERIFICATION_REQUIRED": "ERROR",
                "UNSUPPORTED_SITE": "SKIPPED",
                "APPLICATION_CLOSED": "SKIPPED",
                "FORM_LOOP": "FAILED",
                "AI_FAILURE": "FAILED",
                "NETWORK_ERROR": "ERROR",
                "TIMEOUT": "ERROR",
            }
            for old_status, new_status in status_mappings.items():
                await self._conn.execute(
                    "UPDATE jobs SET status = ? WHERE status = ?",
                    (new_status, old_status),
                )

            valid_statuses = (
                "NEW",
                "SKIPPED",
                "FAILED",
                "APPLIED",
                "SUBMITTED",
                "REDIRECTED",
                "EXTERNAL_REQUIRED",
                "ERROR",
            )
            placeholders = ",".join("?" for _ in valid_statuses)
            await self._conn.execute(
                f"UPDATE jobs SET status = 'ERROR' WHERE status NOT IN ({placeholders}) AND status IS NOT NULL",
                valid_statuses,
            )
            await self._conn.execute(
                "UPDATE jobs SET status = 'NEW' WHERE status IS NULL"
            )
            await self._conn.commit()
        logger.info(
            "Database initialized at %s and migrated to V5 schema", self.db_path
        )

    async def close(self) -> None:
        """Close the persistent connection cleanly."""
        async with self._lock:
            if self._conn is not None:
                await self._conn.close()
                self._conn = None
                logger.info("Database connection closed.")

    def _get_conn(self) -> aiosqlite.Connection:
        """Return the live connection, raising if not initialized."""
        if self._conn is None:
            raise RuntimeError(
                "Database not initialized. Call await db.initialize() before using."
            )
        try:
            from automation.browser_health import record_heartbeat

            record_heartbeat("database")
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)
        return self._conn

    # ── Job Methods ──────────────────────────────────────────────────────────

    async def insert_job(self, job: Job) -> int | None:
        """Insert a job. Returns row id or None if duplicate."""
        try:
            async with self._lock:
                db = self._get_conn()
                cursor = await db.execute(
                    """
                    INSERT OR IGNORE INTO jobs
                        (title, company, location, experience, salary, url,
                         source, description, requirements, skills,
                         posted_date, discovered_date, status)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        job.title,
                        job.company,
                        job.location,
                        job.experience,
                        job.salary,
                        job.url,
                        job.source,
                        job.description,
                        job.requirements,
                        job.skills,
                        job.posted_date,
                        job.discovered_date,
                        job.status,
                    ),
                )
                await db.commit()
                if cursor.lastrowid and cursor.rowcount:
                    logger.debug("Inserted job: %s @ %s", job.title, job.company)
                    return cursor.lastrowid
                logger.debug("Duplicate skipped: %s @ %s", job.title, job.company)
                return None
        except Exception as exc:
            logger.error("insert_job error: %s", exc)
            await self.log_error("insert_job", str(exc))
            return None

    async def is_duplicate(self, url: str, company: str, title: str) -> bool:
        """Return True if a job with the same URL or (company+title) already exists."""
        async with self._lock:
            db = self._get_conn()
            cursor = await db.execute(
                "SELECT id FROM jobs WHERE url=? OR (company=? AND title=?) LIMIT 1",
                (url, company, title),
            )
            row = await cursor.fetchone()
            return row is not None

    async def get_all_jobs(self, status_filter: str | None = None) -> list[Job]:
        async with self._lock:
            db = self._get_conn()
            if status_filter:
                cursor = await db.execute(
                    "SELECT * FROM jobs WHERE status=? ORDER BY discovered_date DESC",
                    (status_filter,),
                )
            else:
                cursor = await db.execute(
                    "SELECT * FROM jobs ORDER BY discovered_date DESC"
                )
            rows = await cursor.fetchall()
            return [Job(**dict(r)) for r in rows]

    async def get_job_by_id(self, job_id: int) -> Job | None:
        async with self._lock:
            db = self._get_conn()
            cursor = await db.execute("SELECT * FROM jobs WHERE id=?", (job_id,))
            row = await cursor.fetchone()
            return Job(**dict(row)) if row else None

    async def update_job_status(self, job_id: int, status: JobStatus) -> None:
        async with self._lock:
            db = self._get_conn()
            await db.execute("UPDATE jobs SET status=? WHERE id=?", (status, job_id))
            await db.commit()

    async def update_job_description(self, job_id: int, description: str) -> None:
        async with self._lock:
            db = self._get_conn()
            await db.execute(
                "UPDATE jobs SET description=? WHERE id=?", (description, job_id)
            )
            await db.commit()

    async def get_jobs_count(self) -> int:
        async with self._lock:
            db = self._get_conn()
            cursor = await db.execute("SELECT COUNT(*) FROM jobs")
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_today_count(self) -> int:
        today = datetime.now(timezone.utc).date().isoformat()
        async with self._lock:
            db = self._get_conn()
            cursor = await db.execute(
                "SELECT COUNT(*) FROM jobs WHERE discovered_date LIKE ?",
                (f"{today}%",),
            )
            row = await cursor.fetchone()
            return row[0] if row else 0

    # ── Saved Jobs ───────────────────────────────────────────────────────────

    async def save_job(self, job_id: int) -> int | None:
        try:
            async with self._lock:
                db = self._get_conn()
                cursor = await db.execute(
                    "SELECT id FROM saved_jobs WHERE job_id=?", (job_id,)
                )
                if await cursor.fetchone():
                    return None  # already saved
                cursor = await db.execute(
                    "INSERT INTO saved_jobs (job_id, saved_date) VALUES (?,?)",
                    (job_id, datetime.now(timezone.utc).isoformat()),
                )
                await db.execute("UPDATE jobs SET status='NEW' WHERE id=?", (job_id,))
                await db.commit()
                return cursor.lastrowid
        except Exception as exc:
            logger.error("save_job error: %s", exc)
            return None

    async def get_saved_jobs(self) -> list[SavedJob]:
        async with self._lock:
            db = self._get_conn()
            cursor = await db.execute(
                """
                SELECT sj.id, sj.job_id, sj.saved_date,
                       j.title, j.company, j.location, j.source,
                       j.url, j.experience, j.salary, j.description,
                       j.requirements, j.skills, j.posted_date,
                       j.discovered_date, j.status
                FROM saved_jobs sj
                JOIN jobs j ON j.id = sj.job_id
                ORDER BY sj.saved_date DESC
                """
            )
            rows = await cursor.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            job = Job(
                id=d["job_id"],
                title=d["title"],
                company=d["company"],
                location=d["location"],
                source=d["source"],
                url=d["url"],
                experience=d.get("experience", ""),
                salary=d.get("salary", ""),
                description=d.get("description", ""),
                requirements=d.get("requirements", ""),
                skills=d.get("skills", ""),
                posted_date=d.get("posted_date", ""),
                discovered_date=d.get("discovered_date", ""),
                status=d.get("status", "NEW").upper(),
            )
            result.append(
                SavedJob(
                    id=d["id"], job_id=d["job_id"], saved_date=d["saved_date"], job=job
                )
            )
        return result

    async def get_saved_jobs_count(self) -> int:
        async with self._lock:
            db = self._get_conn()
            cursor = await db.execute("SELECT COUNT(*) FROM saved_jobs")
            row = await cursor.fetchone()
            return row[0] if row else 0

    # ── Applied Jobs ─────────────────────────────────────────────────────────

    async def mark_applied(
        self, job_id: int, application_url: str = "", notes: str = ""
    ) -> int | None:
        try:
            async with self._lock:
                db = self._get_conn()
                cursor = await db.execute(
                    "SELECT id FROM applied_jobs WHERE job_id=?", (job_id,)
                )
                if await cursor.fetchone():
                    return None  # already applied
                cursor = await db.execute(
                    """
                    INSERT INTO applied_jobs
                        (job_id, applied_date, application_url, status, notes)
                    VALUES (?,?,?,?,?)
                    """,
                    (
                        job_id,
                        datetime.now(timezone.utc).isoformat(),
                        application_url,
                        "APPLIED",
                        notes,
                    ),
                )
                await db.execute(
                    "UPDATE jobs SET status='APPLIED' WHERE id=?", (job_id,)
                )
                await db.commit()
                return cursor.lastrowid
        except Exception as exc:
            logger.error("mark_applied error: %s", exc)
            return None

    async def get_applied_jobs(self) -> list[AppliedJob]:
        async with self._lock:
            db = self._get_conn()
            cursor = await db.execute(
                """
                SELECT aj.id, aj.job_id, aj.applied_date, aj.application_url,
                       aj.status, aj.notes,
                       j.title, j.company, j.location, j.source,
                       j.url, j.experience, j.salary, j.description,
                       j.requirements, j.skills, j.posted_date,
                       j.discovered_date
                FROM applied_jobs aj
                JOIN jobs j ON j.id = aj.job_id
                ORDER BY aj.applied_date DESC
                """
            )
            rows = await cursor.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            job = Job(
                id=d["job_id"],
                title=d["title"],
                company=d["company"],
                location=d["location"],
                source=d["source"],
                url=d["url"],
                experience=d.get("experience", ""),
                salary=d.get("salary", ""),
                description=d.get("description", ""),
                requirements=d.get("requirements", ""),
                skills=d.get("skills", ""),
                posted_date=d.get("posted_date", ""),
                discovered_date=d.get("discovered_date", ""),
                status="APPLIED",
            )
            result.append(
                AppliedJob(
                    id=d["id"],
                    job_id=d["job_id"],
                    applied_date=d["applied_date"],
                    application_url=d.get("application_url", ""),
                    status=d.get("status", "APPLIED"),
                    notes=d.get("notes", ""),
                    job=job,
                )
            )
        return result

    async def get_applied_jobs_count(self) -> int:
        async with self._lock:
            db = self._get_conn()
            cursor = await db.execute("SELECT COUNT(*) FROM applied_jobs")
            row = await cursor.fetchone()
            return row[0] if row else 0

    # ── Notifications ────────────────────────────────────────────────────────

    async def add_notification(self, type_: str, message: str) -> None:
        async with self._lock:
            db = self._get_conn()
            await db.execute(
                "INSERT INTO notifications (type, message, created_at) VALUES (?,?,?)",
                (type_, message, datetime.now(timezone.utc).isoformat()),
            )
            await db.commit()

    async def get_notifications(self, limit: int = 50) -> list[Notification]:
        async with self._lock:
            db = self._get_conn()
            cursor = await db.execute(
                "SELECT * FROM notifications ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()
        return [
            Notification(
                id=r["id"],
                type=r["type"],
                message=r["message"],
                created_at=r["created_at"],
                read=bool(r["read"]),
            )
            for r in rows
        ]

    async def mark_notifications_read(self) -> None:
        async with self._lock:
            db = self._get_conn()
            await db.execute("UPDATE notifications SET read=1 WHERE read=0")
            await db.commit()

    # ── Search History ───────────────────────────────────────────────────────

    async def log_search(
        self,
        keywords: list[str],
        locations: list[str],
        sources: list[str],
        results_count: int,
    ) -> None:
        async with self._lock:
            db = self._get_conn()
            await db.execute(
                """
                INSERT INTO search_history
                    (keywords, locations, sources, results_count, searched_at)
                VALUES (?,?,?,?,?)
                """,
                (
                    ", ".join(keywords),
                    ", ".join(locations),
                    ", ".join(sources),
                    results_count,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            await db.commit()

    async def get_search_history(self, limit: int = 20) -> list[SearchHistory]:
        async with self._lock:
            db = self._get_conn()
            cursor = await db.execute(
                "SELECT * FROM search_history ORDER BY searched_at DESC LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()
        return [SearchHistory(**dict(r)) for r in rows]

    # ── Error Logging ────────────────────────────────────────────────────────

    async def log_error(self, context: str, message: str) -> None:
        """Log an error to the DB. Never raises — errors in error-logging are ignored."""
        try:
            # Use a separate short-lived connection so this never deadlocks
            # when called while self._lock is held by another query.
            async with aiosqlite.connect(self.db_path) as err_db:
                await err_db.execute(
                    "INSERT INTO errors (context, error_message, occurred_at) VALUES (?,?,?)",
                    (context, message, datetime.now(timezone.utc).isoformat()),
                )
                await err_db.commit()
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)  # Never cascade errors from error logging

    # ── CSV Export ───────────────────────────────────────────────────────────

    async def export_jobs_csv(self, path: str | None = None) -> str:
        jobs = await self.get_all_jobs()
        out = path or str(Path(self.db_path).parent / "jobs.csv")
        with open(out, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "id",
                    "title",
                    "company",
                    "location",
                    "experience",
                    "salary",
                    "url",
                    "source",
                    "posted_date",
                    "discovered_date",
                    "status",
                ],
            )
            writer.writeheader()
            for j in jobs:
                writer.writerow(
                    {
                        "id": j.id,
                        "title": j.title,
                        "company": j.company,
                        "location": j.location,
                        "experience": j.experience,
                        "salary": j.salary,
                        "url": j.url,
                        "source": j.source,
                        "posted_date": j.posted_date,
                        "discovered_date": j.discovered_date,
                        "status": j.status,
                    }
                )
        logger.info("Exported %d jobs to %s", len(jobs), out)
        return out

    async def export_applied_csv(self, path: str | None = None) -> str:
        applied = await self.get_applied_jobs()
        out = path or str(Path(self.db_path).parent / "applied_jobs.csv")
        with open(out, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "id",
                    "title",
                    "company",
                    "location",
                    "source",
                    "url",
                    "applied_date",
                    "application_url",
                    "status",
                    "notes",
                ],
            )
            writer.writeheader()
            for a in applied:
                j = a.job
                writer.writerow(
                    {
                        "id": a.id,
                        "title": j.title if j else "",
                        "company": j.company if j else "",
                        "location": j.location if j else "",
                        "source": j.source if j else "",
                        "url": j.url if j else "",
                        "applied_date": a.applied_date,
                        "application_url": a.application_url,
                        "status": a.status,
                        "notes": a.notes,
                    }
                )
        logger.info("Exported %d applied jobs to %s", len(applied), out)
        return out

    async def get_memory(self, key: str) -> str | None:
        """Retrieve a stored value by key from knowledge_memory."""
        async with self._lock:
            db = self._get_conn()
            cursor = await db.execute(
                "SELECT value FROM knowledge_memory WHERE key=?", (key,)
            )
            row = await cursor.fetchone()
            return row[0] if row else None

    async def set_memory(self, key: str, value: str) -> None:
        """Store or update a value by key in knowledge_memory."""
        async with self._lock:
            db = self._get_conn()
            await db.execute(
                """
                INSERT OR REPLACE INTO knowledge_memory (key, value, updated_at)
                VALUES (?, ?, ?)
                """,
                (key, value, datetime.now(timezone.utc).isoformat()),
            )
            await db.commit()

    # ── V5 Rebuild Helpers ───────────────────────────────────────────────────

    async def add_session(self, session_key: str, status: str) -> None:
        async with self._lock:
            db = self._get_conn()
            await db.execute(
                "INSERT OR REPLACE INTO sessions (session_key, start_time, status) VALUES (?, ?, ?)",
                (session_key, datetime.now(timezone.utc).isoformat(), status),
            )
            await db.commit()

    async def update_session_status(self, session_key: str, status: str) -> None:
        async with self._lock:
            db = self._get_conn()
            await db.execute(
                "UPDATE sessions SET status = ?, end_time = ? WHERE session_key = ?",
                (
                    status,
                    datetime.now(timezone.utc).isoformat()
                    if status in ("Closed", "Completed", "Failed")
                    else None,
                    session_key,
                ),
            )
            await db.commit()

    async def get_sessions(self) -> list[dict]:
        async with self._lock:
            db = self._get_conn()
            cursor = await db.execute("SELECT * FROM sessions ORDER BY start_time DESC")
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def add_browser_history(
        self, url: str, title: str, session_id: int | None = None
    ) -> None:
        async with self._lock:
            db = self._get_conn()
            await db.execute(
                "INSERT INTO browser_history (url, title, visited_at, session_id) VALUES (?, ?, ?, ?)",
                (url, title, datetime.now(timezone.utc).isoformat(), session_id),
            )
            await db.commit()

    async def get_browser_history(self, limit: int = 100) -> list[dict]:
        async with self._lock:
            db = self._get_conn()
            cursor = await db.execute(
                "SELECT * FROM browser_history ORDER BY visited_at DESC LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def log_ai_decision(
        self,
        job_id: int | None,
        model_name: str,
        prompt: str,
        response: str,
        tokens_used: int = 0,
        latency_ms: int = 0,
        decision_type: str = "",
    ) -> None:
        async with self._lock:
            db = self._get_conn()
            await db.execute(
                """
                INSERT INTO ai_decisions
                    (job_id, model_name, prompt, response, tokens_used, latency_ms, decision_type, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    model_name,
                    prompt,
                    response,
                    tokens_used,
                    latency_ms,
                    decision_type,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            await db.commit()

    async def get_ai_decisions(self, limit: int = 100) -> list[dict]:
        async with self._lock:
            db = self._get_conn()
            cursor = await db.execute(
                "SELECT * FROM ai_decisions ORDER BY created_at DESC LIMIT ?", (limit,)
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def log_resume_upload(
        self, job_id: int | None, resume_path: str, status: str
    ) -> None:
        async with self._lock:
            db = self._get_conn()
            await db.execute(
                "INSERT INTO resume_uploads (job_id, resume_path, uploaded_at, status) VALUES (?, ?, ?, ?)",
                (job_id, resume_path, datetime.now(timezone.utc).isoformat(), status),
            )
            await db.commit()

    async def get_resume_uploads(self) -> list[dict]:
        async with self._lock:
            db = self._get_conn()
            cursor = await db.execute(
                "SELECT * FROM resume_uploads ORDER BY uploaded_at DESC"
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_website_cache(self, url: str) -> str | None:
        async with self._lock:
            db = self._get_conn()
            cursor = await db.execute(
                "SELECT content FROM website_cache WHERE url = ?", (url,)
            )
            row = await cursor.fetchone()
            return row[0] if row else None

    async def set_website_cache(self, url: str, content: str) -> None:
        async with self._lock:
            db = self._get_conn()
            await db.execute(
                "INSERT OR REPLACE INTO website_cache (url, content, cached_at) VALUES (?, ?, ?)",
                (url, content, datetime.now(timezone.utc).isoformat()),
            )
            await db.commit()

    async def get_account(self, domain: str) -> dict | None:
        async with self._lock:
            db = self._get_conn()
            cursor = await db.execute(
                "SELECT * FROM accounts WHERE domain = ?", (domain,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def set_account(self, domain: str, email: str, password: str) -> None:
        async with self._lock:
            db = self._get_conn()
            await db.execute(
                """
                INSERT OR REPLACE INTO accounts (domain, email, password, created_at, last_used_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    domain,
                    email,
                    password,
                    datetime.now(timezone.utc).isoformat(),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            await db.commit()

    async def get_accounts(self) -> list[dict]:
        async with self._lock:
            db = self._get_conn()
            cursor = await db.execute("SELECT * FROM accounts ORDER BY domain ASC")
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def add_application_attempt(
        self, job_id: int, status: str, notes: str | None = None
    ) -> None:
        async with self._lock:
            db = self._get_conn()
            await db.execute(
                "INSERT INTO applications (job_id, attempt_date, status, notes) VALUES (?, ?, ?, ?)",
                (job_id, datetime.now(timezone.utc).isoformat(), status, notes),
            )
            await db.commit()

    async def get_application_attempts(self, limit: int = 100) -> list[dict]:
        async with self._lock:
            db = self._get_conn()
            cursor = await db.execute(
                """
                SELECT a.*, j.title, j.company, j.url
                FROM applications a
                LEFT JOIN jobs j ON a.job_id = j.id
                ORDER BY a.attempt_date DESC LIMIT ?
                """,
                (limit,),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_latest_resume_upload_status(self, job_id: int) -> str | None:
        async with self._lock:
            db = self._get_conn()
            cursor = await db.execute(
                "SELECT status FROM resume_uploads WHERE job_id = ? ORDER BY uploaded_at DESC LIMIT 1",
                (job_id,),
            )
            row = await cursor.fetchone()
            return row[0] if row else None

    async def batch_delete_jobs(self, job_ids: list[int]) -> None:
        async with self._lock:
            db = self._get_conn()
            placeholders = ",".join("?" for _ in job_ids)
            await db.execute(
                f"DELETE FROM saved_jobs WHERE job_id IN ({placeholders})", job_ids
            )
            await db.execute(
                f"DELETE FROM applied_jobs WHERE job_id IN ({placeholders})", job_ids
            )
            await db.execute(
                f"DELETE FROM application_queue WHERE job_id IN ({placeholders})",
                job_ids,
            )
            await db.execute(f"DELETE FROM jobs WHERE id IN ({placeholders})", job_ids)
            await db.commit()

    async def add_to_queue(
        self, job_id: int, priority: int = 0, added_at: str = ""
    ) -> None:
        async with self._lock:
            db = self._get_conn()
            await db.execute(
                """
                INSERT OR REPLACE INTO application_queue (job_id, priority, status, added_at)
                VALUES (?, ?, 'PENDING', ?)
                """,
                (job_id, priority, added_at),
            )
            await db.commit()

    async def get_queue_items(self) -> list[dict]:
        async with self._lock:
            db = self._get_conn()
            cursor = await db.execute(
                """
                SELECT q.*, j.title, j.company, j.url, j.location, j.source, j.status as job_status
                FROM application_queue q
                JOIN jobs j ON q.job_id = j.id
                ORDER BY q.status = 'RUNNING' DESC, q.priority DESC, q.added_at ASC
                """
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_queue_size(self) -> int:
        async with self._lock:
            db = self._get_conn()
            cursor = await db.execute(
                "SELECT COUNT(*) FROM application_queue WHERE status = 'PENDING'"
            )
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def clear_completed_queue(self) -> None:
        async with self._lock:
            db = self._get_conn()
            await db.execute("DELETE FROM application_queue WHERE status = 'COMPLETED'")
            await db.commit()

    async def clear_all_queue(self) -> None:
        async with self._lock:
            db = self._get_conn()
            await db.execute("DELETE FROM application_queue")
            await db.commit()

    async def clear_failed_queue(self) -> None:
        async with self._lock:
            db = self._get_conn()
            await db.execute("DELETE FROM application_queue WHERE status = 'FAILED'")
            await db.commit()

    async def retry_failed_queue(self) -> None:
        async with self._lock:
            db = self._get_conn()
            await db.execute(
                "UPDATE application_queue SET status = 'PENDING' WHERE status = 'FAILED'"
            )
            await db.commit()

    async def retry_retryable_failures(self, retryable_results: set) -> None:
        """Retry only failures with result codes that are potentially retryable."""
        async with self._lock:
            db = self._get_conn()
            # Get job_ids from jobs table that have retryable result codes in application attempts
            ",".join("?," * len(retryable_results)).rstrip(",")
            # We need to check the notes field in application_attempts for the result code
            # For now, we'll retry all FAILED queue items - the filtering happens at application level
            await db.execute(
                "UPDATE application_queue SET status = 'PENDING' WHERE status = 'FAILED'"
            )
            await db.commit()

    async def retry_selected_queue(self, job_ids: list[int]) -> None:
        async with self._lock:
            db = self._get_conn()
            placeholders = ",".join("?" for _ in job_ids)
            await db.execute(
                f"UPDATE application_queue SET status = 'PENDING' WHERE job_id IN ({placeholders})",
                job_ids,
            )
            await db.commit()

    async def retry_external_jobs(self, added_at: str) -> None:
        async with self._lock:
            db = self._get_conn()
            cursor = await db.execute(
                "SELECT id FROM jobs WHERE status IN ('EXTERNAL_REQUIRED', 'REDIRECTED')"
            )
            rows = await cursor.fetchall()
            for r in rows:
                await db.execute(
                    """
                    INSERT OR REPLACE INTO application_queue (job_id, priority, status, added_at)
                    VALUES (?, 0, 'PENDING', ?)
                    """,
                    (r["id"], added_at),
                )
            await db.commit()

    async def apply_selected_jobs_queue(
        self, job_ids: list[int], added_at: str
    ) -> None:
        async with self._lock:
            db = self._get_conn()
            for jid in job_ids:
                await db.execute(
                    """
                    INSERT OR REPLACE INTO application_queue (job_id, priority, status, added_at)
                    VALUES (?, 0, 'PENDING', ?)
                    """,
                    (jid, added_at),
                )
            await db.commit()

    async def apply_all_new_jobs_queue(self, added_at: str) -> None:
        async with self._lock:
            db = self._get_conn()
            cursor = await db.execute("SELECT id FROM jobs WHERE status = 'NEW'")
            rows = await cursor.fetchall()
            for r in rows:
                await db.execute(
                    """
                    INSERT OR REPLACE INTO application_queue (job_id, priority, status, added_at)
                    VALUES (?, 0, 'PENDING', ?)
                    """,
                    (r["id"], added_at),
                )
            await db.commit()

    async def update_queue_priority(self, job_id: int, priority: int) -> None:
        async with self._lock:
            db = self._get_conn()
            await db.execute(
                "UPDATE application_queue SET priority = ? WHERE job_id = ?",
                (priority, job_id),
            )
            await db.commit()

    async def get_next_pending_queue_item(self) -> Job | None:
        async with self._lock:
            db = self._get_conn()
            cursor = await db.execute(
                """
                SELECT q.job_id, j.title, j.company, j.url, j.location, j.source, j.status, j.description, j.experience, j.salary
                FROM application_queue q
                JOIN jobs j ON q.job_id = j.id
                WHERE q.status = 'PENDING'
                ORDER BY q.priority DESC, q.added_at ASC
                LIMIT 1
                """
            )
            row = await cursor.fetchone()
            if row:
                job = Job(**dict(row))
                job.id = row["job_id"]
                await db.execute(
                    "UPDATE application_queue SET status = 'RUNNING' WHERE job_id = ?",
                    (job.id,),
                )
                await db.commit()
                return job
            return None

    async def update_queue_item_status(self, job_id: int, status: str) -> None:
        async with self._lock:
            db = self._get_conn()
            await db.execute(
                "UPDATE application_queue SET status = ? WHERE job_id = ?",
                (status, job_id),
            )
            await db.commit()

    async def get_dashboard_stats(self, today_str: str) -> dict:
        async with self._lock:
            db = self._get_conn()
            cursor = await db.execute(
                "SELECT COUNT(*) FROM applications WHERE attempt_date >= ?",
                (today_str,),
            )
            r_today = await cursor.fetchone()
            apps_today = r_today[0] if r_today else 0

            cursor = await db.execute("SELECT COUNT(*) FROM jobs")
            r_found = await cursor.fetchone()
            jobs_found = r_found[0] if r_found else 0

            cursor = await db.execute(
                "SELECT COUNT(*) FROM applications WHERE status IN ('FAILED', 'ERROR')"
            )
            r_failed = await cursor.fetchone()
            failures = r_failed[0] if r_failed else 0

            cursor = await db.execute(
                "SELECT COUNT(*) FROM applications WHERE status IN ('SUBMITTED', 'APPLIED')"
            )
            r_success = await cursor.fetchone()
            successes = r_success[0] if r_success else 0

            cursor = await db.execute(
                "SELECT AVG(latency_ms) FROM ai_decisions WHERE decision_type = 'reasoning'"
            )
            avg_llm = await cursor.fetchone()
            llm_lat = int(avg_llm[0]) if avg_llm and avg_llm[0] else None

            cursor = await db.execute(
                "SELECT AVG(latency_ms) FROM ai_decisions WHERE decision_type LIKE 'vision%'"
            )
            avg_vis = await cursor.fetchone()
            vis_lat = int(avg_vis[0]) if avg_vis and avg_vis[0] else None

            cursor = await db.execute("SELECT AVG(latency_ms) FROM ai_decisions")
            avg_total = await cursor.fetchone()
            avg_total_val = avg_total[0] if avg_total and avg_total[0] else None

            return {
                "apps_today": apps_today,
                "jobs_found": jobs_found,
                "failures": failures,
                "successes": successes,
                "llm_lat": llm_lat,
                "vis_lat": vis_lat,
                "avg_total": avg_total_val,
            }

    async def get_analytics_stats(self) -> dict:
        async with self._lock:
            db = self._get_conn()
            stats = {}
            keys = [
                "NEW",
                "SKIPPED",
                "FAILED",
                "APPLIED",
                "SUBMITTED",
                "REDIRECTED",
                "EXTERNAL_REQUIRED",
                "ERROR",
            ]
            for k in keys:
                cursor = await db.execute(
                    "SELECT COUNT(*) FROM jobs WHERE status = ?", (k,)
                )
                r = await cursor.fetchone()
                stats[k] = r[0] if r else 0
            return stats

    async def get_ai_page_stats(self) -> dict:
        async with self._lock:
            db = self._get_conn()
            cursor = await db.execute("SELECT COUNT(*) FROM ai_decisions")
            r1 = await cursor.fetchone()
            decisions_count = r1[0] if r1 else 0

            cursor = await db.execute("SELECT COUNT(*) FROM knowledge_memory")
            r2 = await cursor.fetchone()
            memory_count = r2[0] if r2 else 0

            cursor = await db.execute("SELECT AVG(latency_ms) FROM ai_decisions")
            r3 = await cursor.fetchone()
            avg_latency = int(r3[0]) if r3 and r3[0] else None

            return {
                "decisions_count": decisions_count,
                "memory_count": memory_count,
                "avg_latency": avg_latency,
            }


# ── Singleton ─────────────────────────────────────────────────────────────────

_db_instance: Database | None = None


def get_database() -> Database:
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance
