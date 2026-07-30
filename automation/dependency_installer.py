"""
Robust Automatic Dependency Installer Engine.
Handles automatic detection, secure installation, live logging, and validation of dependencies.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

from core.logger import get_logger

logger = get_logger(__name__)


class DependencyInstaller:
    """
    Manages package installation securely using sys.executable.
    Streams logs in real-time, upgrades core pip components, and validates imports.
    """

    def __init__(self) -> None:
        self.python_exe = sys.executable
        self.log_file = Path("logs/installer.log")
        try:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            # Clear old log if it exists to keep it fresh for this run
            if self.log_file.exists():
                self.log_file.write_text("")
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)

    def _log_to_file(self, msg: str) -> None:
        """Append log directly to installer.log"""
        try:
            with self.log_file.open("a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)

    def run_pip_command(self, args: list[str], log_callback=None) -> bool:
        """
        Executes a pip command, capturing and streaming output.
        Returns True on success, False otherwise.
        """
        cmd = [self.python_exe, "-m", "pip"] + args
        cmd_str = " ".join(cmd)

        self._log_to_file(f"> {cmd_str}")
        if log_callback:
            log_callback(f"> {cmd_str}\n")

        try:
            # We use creationflags=subprocess.CREATE_NO_WINDOW on Windows to prevent popups
            kwargs = {}
            if sys.platform == "win32":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                **kwargs,
            )

            if process.stdout:
                for line in process.stdout:
                    self._log_to_file(line.rstrip())
                    if log_callback:
                        log_callback(line)

            process.wait()
            success = process.returncode == 0
            if not success:
                self._log_to_file(
                    f"Command failed with exit code: {process.returncode}"
                )
                if log_callback:
                    log_callback(
                        f"\n[ERROR] Command failed with exit code: {process.returncode}\n"
                    )
            return success

        except Exception as e:
            err_msg = f"[ERROR] Failed to execute pip: {e}"
            self._log_to_file(err_msg)
            if log_callback:
                log_callback(err_msg + "\n")
            return False

    def upgrade_core(self, log_callback=None) -> bool:
        """Upgrades pip, setuptools, and wheel."""
        if log_callback:
            log_callback("Upgrading core Python tools (pip, setuptools, wheel)...\n")
        return self.run_pip_command(
            [
                "install",
                "--upgrade",
                "pip",
                "setuptools",
                "wheel",
                "--disable-pip-version-check",
                "--quiet",
            ],
            log_callback=log_callback,
        )

    def install_package(self, pip_name: str, log_callback=None) -> bool:
        """Installs a single package."""
        if log_callback:
            log_callback(f"\nInstalling package: {pip_name}...\n")
        return self.run_pip_command(
            ["install", pip_name, "--disable-pip-version-check"],
            log_callback=log_callback,
        )

    def verify_import(self, import_name: str) -> bool:
        """Verifies if a package can be successfully imported."""
        try:
            importlib.invalidate_caches()
            importlib.import_module(import_name)
            return True
        except ImportError:
            return False
        except Exception as e:
            logger.warning("Error while verifying import %s: %s", import_name, e)
            return False
