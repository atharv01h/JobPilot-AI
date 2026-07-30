"""
Centralized logging configuration.
Outputs to both console (coloured) and rotating file handler.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

try:
    import colorlog

    _HAS_COLORLOG = True
except ImportError:
    _HAS_COLORLOG = False

from config.constants import LOG_BACKUP_COUNT, LOG_FILE, LOG_MAX_BYTES

_root_configured = False
_log_path: Path | None = None


class ConsoleLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Secret Masking
        if isinstance(record.msg, str):
            for secret in ["nvapi-", "sk-ant-", "sk-proj-"]:
                if secret in record.msg:
                    record.msg = record.msg.replace(secret, "***")
        if record.levelno >= logging.WARNING:
            return True
        msg = record.getMessage()
        name = record.name
        if name in ("main", "Startup", "StartupAsync", "App") and any(
            x in msg
            for x in (
                "Starting up",
                "PHASE",
                "Phased Startup",
                "Ready",
                "Logging initialized",
            )
        ):
            return True
        if "search" in msg.lower() or "scraper" in msg.lower():
            if any(x in msg.lower() for x in ("started", "finished", "completed")):
                return True
        return bool(any(x in msg for x in ("ApplicationQueue: [START]", "[RESULT]", "Current Application", "Processing application")))


def setup_logging(log_dir: str | None = None) -> None:
    """Configure root logger. Call once from main.py."""
    global _root_configured, _log_path

    if _root_configured:
        return

    # Resolve log directory
    if log_dir:
        log_path = Path(log_dir) / "job_assistant.log"
    else:
        log_path = Path(LOG_FILE)

    log_path.parent.mkdir(parents=True, exist_ok=True)
    _log_path = log_path

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # ── File handler ─────────────────────────────────────────────────────────
    file_fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh = RotatingFileHandler(
        str(log_path),
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(file_fmt)
    root.addHandler(fh)

    # ── Console handler ──────────────────────────────────────────────────────
    if _HAS_COLORLOG:
        console_fmt = colorlog.ColoredFormatter(
            "%(log_color)s%(asctime)s%(reset)s | %(log_color)s%(levelname)-8s%(reset)s | %(cyan)s%(name)s%(reset)s | %(message)s",
            datefmt="%H:%M:%S",
            log_colors={
                "DEBUG": "white",
                "INFO": "green",
                "WARNING": "yellow",
                "ERROR": "red",
                "CRITICAL": "bold_red",
            },
        )
    else:
        console_fmt = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%H:%M:%S",
        )

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(console_fmt)
    ch.addFilter(ConsoleLogFilter())
    root.addHandler(ch)

    # Silence noisy third-party loggers
    for noisy in ("httpx", "httpcore", "playwright", "asyncio", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _root_configured = True
    root.info("Logging initialized -> %s", log_path)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger. setup_logging() must have been called first."""
    return logging.getLogger(name)


def get_log_path() -> Path | None:
    return _log_path
