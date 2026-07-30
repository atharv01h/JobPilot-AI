"""
cdp_connector.py — Pure, stateless CDP helper functions.

All Brave process management and CDP connection logic lives here.
Nothing else in the project should shell-out to tasklist, taskkill, or
call p.chromium.connect_over_cdp directly — use these functions instead.
"""

from __future__ import annotations

import asyncio
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

from config.constants import (
    BRAVE_EXE_PATH,
    CDP_LAUNCH_POLL_ATTEMPTS,
    CDP_LAUNCH_POLL_INTERVAL,
    CDP_MAX_LAUNCH_ATTEMPTS,
    CDP_PORT,
    CDP_TIMEOUT_CONNECT,
    CDP_TIMEOUT_HTTP,
)
from core.logger import get_logger

logger = get_logger(__name__)


# ── Low-level process utilities ───────────────────────────────────────────────


def is_brave_running() -> bool:
    """Return True if any brave.exe process is running."""
    try:
        out = subprocess.check_output(
            'tasklist /FI "IMAGENAME eq brave.exe"',
            shell=True,
        ).decode("utf-8", errors="ignore")
        return "brave.exe" in out.lower()
    except Exception as exc:
        logger.debug("is_brave_running check failed: %s", exc)
        return False


def is_cdp_port_open(port: int = CDP_PORT) -> bool:
    """Return True if the CDP HTTP endpoint responds with 200."""
    try:
        r = httpx.get(
            f"http://127.0.0.1:{port}/json/version",
            timeout=CDP_TIMEOUT_HTTP,
        )
        return r.status_code == 200
    except Exception:
        return False


def get_cdp_websocket_url(port: int = CDP_PORT) -> str | None:
    """Fetch the webSocketDebuggerUrl from the CDP JSON endpoint."""
    try:
        r = httpx.get(
            f"http://127.0.0.1:{port}/json/version",
            timeout=CDP_TIMEOUT_HTTP,
        )
        if r.status_code == 200:
            return r.json().get("webSocketDebuggerUrl")
    except Exception as exc:
        logger.debug("get_cdp_websocket_url failed: %s", exc)
    return None


def kill_brave() -> None:
    """Terminate all brave.exe processes and wait until gone (max 5s)."""
    logger.info("Terminating Brave processes...")
    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", "brave.exe"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=True,
        )
        for _ in range(10):
            time.sleep(0.5)
            if not is_brave_running():
                logger.debug("Brave processes terminated.")
                return
        logger.warning("Brave processes may still be running after kill attempt.")
    except Exception as exc:
        logger.error("kill_brave failed: %s", exc)


def launch_brave_with_debugging(port: int = CDP_PORT) -> bool:
    """
    Launch Brave with remote debugging enabled.
    Returns True if the launch command succeeded (not necessarily that the
    port is open yet — call wait_for_cdp_port() after this).
    """
    brave_exe = BRAVE_EXE_PATH
    if not Path(brave_exe).exists():
        logger.warning("Brave executable not found at: %s", brave_exe)
        return False

    import os

    local_app_data = os.getenv("LOCALAPPDATA", "")
    if local_app_data:
        brave_profile = (
            Path(local_app_data) / "BraveSoftware" / "Brave-Browser" / "User Data"
        )
    else:
        brave_profile = Path(
            os.path.expandvars(
                "%USERPROFILE%/AppData/Local/BraveSoftware/Brave-Browser/User Data"
            )
        )

    cmd = [
        brave_exe,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={brave_profile.as_posix()}",
        "--profile-directory=Default",
        "--start-maximized",
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
    ]
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logger.info("Brave launched with --remote-debugging-port=%d", port)
        return True
    except Exception as exc:
        logger.error("launch_brave_with_debugging failed: %s", exc)
        return False


def wait_for_cdp_port(
    port: int = CDP_PORT,
    poll_interval: float = CDP_LAUNCH_POLL_INTERVAL,
    max_attempts: int = CDP_LAUNCH_POLL_ATTEMPTS,
) -> bool:
    """
    Synchronous poll until the CDP port responds or we give up.
    Uses time.sleep() — only call from a thread, never from the async loop directly.
    """
    for attempt in range(max_attempts):
        time.sleep(poll_interval)
        if is_cdp_port_open(port):
            logger.debug("CDP port %d open after %d poll(s).", port, attempt + 1)
            return True
    logger.warning("CDP port %d did not open after %d polls.", port, max_attempts)
    return False


async def async_wait_for_cdp_port(
    port: int = CDP_PORT,
    poll_interval: float = CDP_LAUNCH_POLL_INTERVAL,
    max_attempts: int = CDP_LAUNCH_POLL_ATTEMPTS,
) -> bool:
    """
    Async version: polls the CDP port without blocking the event loop.
    """
    for attempt in range(max_attempts):
        await asyncio.sleep(poll_interval)
        if is_cdp_port_open(port):
            logger.debug("CDP port %d open after %d poll(s).", port, attempt + 1)
            return True
    logger.warning("CDP port %d did not open after %d polls.", port, max_attempts)
    return False


# ── High-level "ensure Brave is ready" ───────────────────────────────────────


async def ensure_brave_debug_ready(
    port: int = CDP_PORT,
    max_launch_attempts: int = CDP_MAX_LAUNCH_ATTEMPTS,
) -> bool:
    """
    Ensure Brave is running with the debug port open.

    Strategy:
      1. Port already open → return True immediately.
      2. Brave running but port closed → kill & relaunch.
      3. Brave not running → launch.
      4. Retry up to max_launch_attempts times.
      5. Return False if all attempts fail.
    """
    if is_cdp_port_open(port):
        logger.debug("CDP port %d already open.", port)
        return True

    for attempt in range(1, max_launch_attempts + 1):
        logger.info("CDP not ready — attempt %d/%d", attempt, max_launch_attempts)

        if is_brave_running():
            logger.info(
                "Brave is running but port %d is closed — relaunching with debugging.",
                port,
            )
            await asyncio.to_thread(kill_brave)
            await asyncio.sleep(1.0)

        launched = await asyncio.to_thread(launch_brave_with_debugging, port)
        if not launched:
            logger.error("Brave launch command failed on attempt %d.", attempt)
            continue

        port_opened = await async_wait_for_cdp_port(port)
        if port_opened:
            logger.info("Brave CDP port %d ready after %d attempt(s).", port, attempt)
            return True

        logger.warning("Brave launched but port did not open — will retry.")
        await asyncio.to_thread(kill_brave)
        await asyncio.sleep(1.0)

    logger.error(
        "Failed to bring Brave CDP port %d up after %d attempts.",
        port,
        max_launch_attempts,
    )
    return False


# ── CDP Connection ────────────────────────────────────────────────────────────


async def connect_cdp(p: Any, port: int = CDP_PORT) -> Any:
    """
    Connect to an already-running Brave via CDP.
    Fetches the WebSocket URL first (more reliable than connecting by HTTP URL directly).
    Raises on failure — callers should handle exceptions.
    """
    ws_url = get_cdp_websocket_url(port)
    if not ws_url:
        logger.warning(
            "Could not get WebSocket URL — falling back to http://127.0.0.1:%d", port
        )
        ws_url = f"http://127.0.0.1:{port}"

    logger.debug("Connecting over CDP to: %s", ws_url)
    browser = await asyncio.wait_for(
        p.chromium.connect_over_cdp(ws_url),
        timeout=CDP_TIMEOUT_CONNECT,
    )
    logger.info("CDP connection established: %s", ws_url)
    return browser


def close_excess_brave_tabs(port: int = CDP_PORT) -> None:
    """
    Close all but 1 Brave tab via CDP REST API.
    Prevents DownloadsWatchdog from flooding the event bus with TabCreatedEvents
    which can deadlock browser-use agents attached to Brave.
    """
    try:
        resp = httpx.get(f"http://127.0.0.1:{port}/json", timeout=CDP_TIMEOUT_HTTP)
        tabs = [t for t in resp.json() if t.get("type") == "page"]
        if len(tabs) <= 1:
            return
        logger.info(
            "Closing %d excess Brave tab(s) before agent connects.", len(tabs) - 1
        )
        tabs_to_close = tabs[:-1]  # keep the most-recently-opened tab
        for tab in tabs_to_close:
            tab_id = tab.get("id", "")
            if tab_id:
                try:
                    httpx.get(
                        f"http://127.0.0.1:{port}/json/close/{tab_id}",
                        timeout=CDP_TIMEOUT_HTTP,
                    )
                except Exception as _exc:
                    logger.debug("Suppressed: %s", _exc)
        time.sleep(0.3)
    except Exception as exc:
        logger.debug("close_excess_brave_tabs: %s", exc)
