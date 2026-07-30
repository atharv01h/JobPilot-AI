"""
JobPilot AI — Entry Point
======================================
Run with: python main.py
"""

from __future__ import annotations

import sys

# ── Suppress PyTorch Dataloader Warnings ─────────────────────────────────────
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=UserWarning, message=".*pin_memory.*")

# ── Windows: force UTF-8 stdout to handle emoji in logs ──────────────────────
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore


# ── Ensure project root is on sys.path ───────────────────────────────────────
_ROOT = Path(__file__).parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ── Load environment variables first ─────────────────────────────────────────
from dotenv import load_dotenv

load_dotenv(_ROOT / ".env", override=False)

# ── Setup logging ─────────────────────────────────────────────────────────────
from config.settings import get_settings
from core.logger import setup_logging

settings = get_settings()
setup_logging(log_dir=settings.log_dir)

from core.logger import get_logger

logger = get_logger("main")
logger.info("=" * 60)
logger.info("  JobPilot AI  —  Starting up")
logger.info("=" * 60)
logger.info("Resume : %s", settings.resume_path)
logger.info("Profile: %s", settings.profile_path)
logger.info("DB     : %s", settings.db_path)
logger.info("Model  : %s (%s)", settings.llm_model, settings.llm_provider)

# ── Launch GUI ────────────────────────────────────────────────────────────────


def main() -> None:
    try:
        from gui.app import App

        app = App()
        app.mainloop()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as exc:
        logger.exception("Fatal error: %s", exc)
        raise


if __name__ == "__main__":
    main()
