"""
ServiceRegistry — Central service registry for JobPilot AI.
Provides clean service registration, lookup, and startup self-testing.
"""

from __future__ import annotations

import os
from typing import Any

from core.logger import get_logger

logger = get_logger(__name__)


class ServiceRegistry:
    _registry: dict[str, Any] = {}

    @classmethod
    def register(cls, name: str, service: Any) -> None:
        cls._registry[name.lower()] = service
        logger.info("ServiceRegistry: Registered service '%s'", name)

    @classmethod
    def get(cls, name: str) -> Any:
        name_lower = name.lower()
        if name_lower in cls._registry:
            return cls._registry[name_lower]

        # Dynamic import fallback to prevent circular dependencies
        try:
            if name_lower == "browsermanager":
                from automation.browser_manager import get_browser_manager

                cls._registry[name_lower] = get_browser_manager()
            elif name_lower == "profileservice":
                from services.profile_service import get_profile_service

                cls._registry[name_lower] = get_profile_service()
            elif name_lower == "resumeservice":
                from services.resume_service import get_resume_service

                cls._registry[name_lower] = get_resume_service()
            elif name_lower == "formservice":
                from services.form_service import get_form_service

                cls._registry[name_lower] = get_form_service()
            elif name_lower == "visionservice":
                from automation.vision_engine import get_vision_engine

                cls._registry[name_lower] = get_vision_engine()
            elif name_lower == "planner":
                from automation.smart_ai import SmartAIOrchestrator

                # Returns the class for instantiating
                return SmartAIOrchestrator
            elif name_lower == "recovery":
                from automation.browser_health import get_health_monitor

                cls._registry[name_lower] = get_health_monitor()
            elif name_lower == "websitemodules":
                from automation.website_modules import get_website_module

                return get_website_module
            elif name_lower == "queue":
                from services.queue_manager import get_job_queue_manager

                cls._registry[name_lower] = get_job_queue_manager()
            elif name_lower == "statemanager":
                from services.state_manager import get_state_manager

                cls._registry[name_lower] = get_state_manager()
            elif name_lower == "aisearchservice":
                from services.ai_search_service import get_ai_search_service

                cls._registry[name_lower] = get_ai_search_service()
        except Exception as exc:
            logger.error(
                "ServiceRegistry: Failed to load service '%s' dynamically: %s",
                name,
                exc,
            )
            return None

        return cls._registry.get(name_lower)

    @classmethod
    def clear(cls) -> None:
        cls._registry.clear()

    @classmethod
    async def perform_self_test(cls) -> bool:
        """
        Executes a complete self-test on configuration, services, files, database, and models.
        Prints a detailed report and returns True if all essential components pass.
        """
        report = []
        is_essential_ok = True

        print("\n============================================================")
        print("                STARTUP SELF TEST BEGINS                    ")
        print("============================================================\n")

        # 1. Imports / Services Load Check
        services_to_check = {
            "ProfileService": True,
            "ResumeService": True,
            "FormService": True,
            "VisionService": False,  # Non-essential
            "Planner": True,
            "BrowserManager": True,
            "Recovery": False,  # Non-essential
            "WebsiteModules": True,
            "Queue": True,
            "StateManager": True,
        }

        for s_name, is_essential in services_to_check.items():
            try:
                svc = cls.get(s_name)
                if svc is not None:
                    report.append((f"Service Load: {s_name}", "PASS", ""))
                    if s_name == "VisionService" and hasattr(svc, "validate_endpoint"):
                        is_valid = await svc.validate_endpoint()
                        if is_valid:
                            report.append(
                                (
                                    "Vision Service Endpoint Validation",
                                    "PASS",
                                    "Endpoint verified and active",
                                )
                            )
                        else:
                            report.append(
                                (
                                    "Vision Service Endpoint Validation",
                                    "FAIL",
                                    "Endpoint validation failed; vision gracefully disabled",
                                )
                            )
                else:
                    raise ValueError("Returned None")
            except Exception as exc:
                err_msg = f"Failed to load {s_name}: {exc}"
                report.append((f"Service Load: {s_name}", "FAIL", err_msg))
                if is_essential:
                    is_essential_ok = False

        # 2. Settings & Configuration
        try:
            from config.settings import get_settings

            settings = get_settings()
            report.append(("Configuration Settings", "PASS", ""))
        except Exception as exc:
            report.append(("Configuration Settings", "FAIL", str(exc)))
            is_essential_ok = False
            settings = None

        # 3. Resume Path Validation
        if settings:
            try:
                resume_svc = cls.get("ResumeService")
                err = resume_svc.validate() if resume_svc else "ResumeService missing"
                if err:
                    report.append(("Resume File Validation", "FAIL", err))
                    is_essential_ok = False
                else:
                    report.append(
                        (
                            "Resume File Validation",
                            "PASS",
                            f"Path: {resume_svc.path_str}",
                        )
                    )
            except Exception as exc:
                report.append(("Resume File Validation", "FAIL", str(exc)))
                is_essential_ok = False
        else:
            report.append(("Resume File Validation", "FAIL", "No settings available"))
            is_essential_ok = False

        # 4. Form Path Validation
        if settings:
            try:
                form_svc = cls.get("FormService")
                if form_svc and form_svc.is_loaded:
                    report.append(
                        ("Form File Validation", "PASS", f"Path: {form_svc.form_path}")
                    )
                else:
                    report.append(
                        (
                            "Form File Validation",
                            "FAIL",
                            f"Form file not loaded or missing: {settings.form_path}",
                        )
                    )
                    is_essential_ok = False
            except Exception as exc:
                report.append(("Form File Validation", "FAIL", str(exc)))
                is_essential_ok = False
        else:
            report.append(("Form File Validation", "FAIL", "No settings available"))
            is_essential_ok = False

        # 5. Database Connection
        try:
            from core.database import get_database

            db = get_database()
            # Test simple call
            cnt = await db.get_jobs_count()
            report.append(("Database Connection & Query", "PASS", f"Jobs count: {cnt}"))
        except Exception as exc:
            report.append(("Database Connection & Query", "FAIL", str(exc)))
            is_essential_ok = False

        # 6. Playwright & Brave Executable
        try:
            from config.constants import BRAVE_EXE_PATH

            if os.path.exists(BRAVE_EXE_PATH):
                report.append(
                    (
                        "Brave Executable Check",
                        "PASS",
                        f"Brave found at: {BRAVE_EXE_PATH}",
                    )
                )
            else:
                report.append(
                    (
                        "Brave Executable Check",
                        "FAIL",
                        f"Brave executable not found at: {BRAVE_EXE_PATH}",
                    )
                )
                is_essential_ok = False
        except Exception as exc:
            report.append(("Brave Executable Check", "FAIL", str(exc)))
            is_essential_ok = False

        # 7. LLM Reasoning Model & API Key Check
        if settings:
            if settings.llm_api_key:
                report.append(("NVIDIA NIM API Key", "PASS", ""))
            else:
                report.append(
                    (
                        "NVIDIA NIM API Key",
                        "FAIL",
                        "LLM_API_KEY environment variable is empty",
                    )
                )
                is_essential_ok = False
        else:
            report.append(("NVIDIA NIM API Key", "FAIL", "No settings available"))
            is_essential_ok = False

        # Print the detailed self-test report
        print(
            "============================================================\n"
            "                     STARTUP REPORT                         \n"
            "============================================================"
        )
        for item, status, detail in report:
            detail_str = f" ({detail})" if detail else ""
            print(f"[{status:<4}] {item:<30}{detail_str}")
        print("============================================================\n")

        if not is_essential_ok:
            logger.critical(
                "STARTUP SELF TEST FAILED: One or more essential services/components failed to initialize."
            )
            print(
                "CRITICAL: One or more essential services/components failed to initialize. Startup halted."
            )
            return False

        logger.info("Startup self-test completed successfully.")
        print("SUCCESS: Startup self-test passed successfully!\n")
        return True
