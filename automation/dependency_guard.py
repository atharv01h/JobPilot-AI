"""
dependency_guard.py — Startup dependency verifier and auto-installer.

Checks every required package at startup.
If a package is missing:
  1. Attempts silent pip install.
  2. If install fails, disables only the strategy that depends on it.
  3. Never crashes the application.

Usage (in main.py):
    from automation.dependency_guard import ensure_all
    ensure_all()
"""

from __future__ import annotations

import importlib

from core.logger import get_logger

logger = get_logger(__name__)


# ── Package registry ──────────────────────────────────────────────────────────
# (import_name, pip_name, disabled_strategy_flag)
_PACKAGES: list[tuple[str, str, str]] = [
    # (importable name, pip install name, flag set on failure)
    ("pywinauto", "pywinauto", "WINUI_DISABLED"),
    ("pygetwindow", "pygetwindow", "PYGETWINDOW_DISABLED"),
    ("pyautogui", "pyautogui", "PYAUTOGUI_DISABLED"),
    ("win32api", "pywin32", "PYWIN32_DISABLED"),
    ("comtypes", "comtypes", "COMTYPES_DISABLED"),
    ("uiautomation", "uiautomation", "UIAUTOMATION_DISABLED"),
    ("playwright", "playwright", "PLAYWRIGHT_DISABLED"),
    ("cv2", "opencv-python", "OPENCV_DISABLED"),
    # EasyOCR is large — install only if not present, flag failure
    ("easyocr", "easyocr", "EASYOCR_DISABLED"),
    ("PIL", "Pillow", "PILLOW_DISABLED"),
]

# Global flags — other modules can import these to check availability
DISABLED_STRATEGIES: dict[str, bool] = {}


def _is_available(import_name: str) -> bool:
    """Return True if the package is importable."""
    try:
        importlib.import_module(import_name)
        return True
    except ImportError:
        return False





def check_dependencies() -> list[tuple[str, str, str]]:
    """Return a list of missing packages as (import_name, pip_name, flag)."""
    missing = []
    for import_name, pip_name, flag in _PACKAGES:
        if not _is_available(import_name):
            missing.append((import_name, pip_name, flag))
    return missing





def ensure_all() -> None:
    """
    Check every required package.
    Do NOT auto-install missing ones silently.
    Set DISABLED_STRATEGIES flags for packages that are missing.
    """
    logger.info("DependencyGuard: Verifying all required packages (check only)...")
    check_dependencies()

    for import_name, pip_name, flag in _PACKAGES:
        if not _is_available(import_name):
            DISABLED_STRATEGIES[flag] = True

    logger.info(
        "DependencyGuard: Done. Disabled strategies: %s",
        list(DISABLED_STRATEGIES.keys()) or "none",
    )


def is_strategy_disabled(flag: str) -> bool:
    """Return True if a strategy was disabled due to missing dependency."""
    return DISABLED_STRATEGIES.get(flag, False)


def is_winui_available() -> bool:
    """Convenience: True if pywinauto is usable."""
    return not is_strategy_disabled("WINUI_DISABLED")


def is_opencv_available() -> bool:
    """Convenience: True if OpenCV is usable."""
    return not is_strategy_disabled("OPENCV_DISABLED")


def is_easyocr_available() -> bool:
    """Convenience: True if EasyOCR is usable."""
    return not is_strategy_disabled("EASYOCR_DISABLED")


def find_locking_processes(keyword: str = "cv2") -> list[str]:
    """Identify processes holding locks on files matching keyword (e.g. cv2.pyd)."""
    import psutil

    locking = []
    kw = keyword.lower()
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            # Check open files
            try:
                for f in proc.open_files():
                    if kw in f.path.lower():
                        locking.append(f"{proc.info['name']} (PID: {proc.info['pid']})")
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

            # Check memory maps (Windows DLLs/PYDs are loaded as memory maps)
            try:
                for m in proc.memory_maps():
                    if kw in m.path.lower():
                        locking.append(f"{proc.info['name']} (PID: {proc.info['pid']})")
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)
    return list(set(locking))
