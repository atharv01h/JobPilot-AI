"""
Main application window — CustomTkinter dark-mode root window.
Manages sidebar navigation, page switching, async task execution,
and CAPTCHA/login dialog wiring.
"""

from __future__ import annotations

import asyncio
import threading

import customtkinter as ctk

from config.constants import (
    COLORS,
    FONTS,
    WINDOW_MIN_HEIGHT,
    WINDOW_MIN_WIDTH,
)
from core.logger import get_logger
from gui.pages.ai import AIPage
from gui.pages.analytics import AnalyticsPage
from gui.pages.applications import ApplicationsPage
from gui.pages.browser import BrowserPage
from gui.pages.dashboard import DashboardPage
from gui.pages.dependencies import DependenciesPage
from gui.pages.diagnostics import DiagnosticsPage
from gui.pages.jobs import JobsPage
from gui.pages.linkedin_easy_apply import LinkedinEasyApplyPage
from gui.pages.logs_viewer import LogsViewerPage
from gui.pages.profile import ProfilePage
from gui.pages.queue import QueuePage
from gui.pages.resume import ResumePage
from gui.pages.scheduler import SchedulerPage
from gui.pages.settings import SettingsPage

logger = get_logger(__name__)
from gui.sidebar import Sidebar


class PlaceholderPage(ctk.CTkFrame):
    """Fallback frame when a main page fails to construct properly."""

    def __init__(self, master, app: App, page_name: str, error_msg: str, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_primary"], **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        container = ctk.CTkFrame(
            self,
            fg_color=COLORS["bg_card"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
        )
        container.grid(row=0, column=0, padx=40, pady=40, sticky="nsew")
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure((0, 1, 2), weight=1)

        ctk.CTkLabel(
            container,
            text=f"⚠️ Failed to Load '{page_name.title()}' Page",
            font=("Segoe UI", 20, "bold"),
            text_color=COLORS["accent_red"],
        ).grid(row=0, column=0, pady=(20, 10))

        ctk.CTkLabel(
            container,
            text=f"An error occurred during page construction:\n\n{error_msg}\n\nPlease check the application logs for a full stack trace.",
            font=FONTS["body_md"],
            text_color=COLORS["text_primary"],
            justify="center",
            wraplength=600,
        ).grid(row=1, column=0, padx=20, pady=10)

        ctk.CTkButton(
            container,
            text="Retry Load",
            command=lambda: app._retry_load_page(page_name),
            fg_color=COLORS["accent_primary"],
            hover_color=COLORS["bg_hover"],
            font=FONTS["heading_sm"],
        ).grid(row=2, column=0, pady=(10, 20))


class App(ctk.CTk):
    """Root application window."""

    def __init__(self) -> None:
        super().__init__()

        # ── Appearance ────────────────────────────────────────────────────────
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("JobPilot AI")
        self.geometry(f"{WINDOW_MIN_WIDTH}x{WINDOW_MIN_HEIGHT}")
        self.minsize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        self.configure(fg_color=COLORS["bg_primary"])

        # Try to set window icon
        try:
            self.iconbitmap("assets/icon.ico")
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)

        # ── Async loop ────────────────────────────────────────────────────────
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._run_loop, daemon=True, name="AsyncLoop"
        )
        self._loop_thread.start()

        # Run synchronous startup phases (Phases 1, 2, 6, 7, 8)
        self._pages = {}
        self._current_page = None
        self._run_startup_phases_sync()

    # ── Async event loop ──────────────────────────────────────────────────────

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def run_async(self, coro) -> None:
        """Submit a coroutine to the background async loop."""
        asyncio.run_coroutine_threadsafe(coro, self._loop)

    # ── App initialization ────────────────────────────────────────────────────

    def _run_startup_phases_sync(self) -> None:
        """Execute Phase 1, Phase 2 synchronously."""
        s_logger = get_logger("Startup")
        s_logger.info("============================================================")
        s_logger.info("   Executing Phased Startup Sequence (Synchronous Phases)")
        s_logger.info("============================================================")
        self._startup_statuses = {}

        # ── Phase 1: Configuration ──
        try:
            from config.settings import get_settings

            self._settings = get_settings()
            self._startup_statuses["Configuration"] = "SUCCESS"
            s_logger.info("PHASE 1: Configuration -> SUCCESS")
        except Exception as e:
            self._startup_statuses["Configuration"] = "FAILED"
            s_logger.error("PHASE 1: Configuration -> FAILED: %s", e)

        # ── Phase 2: Dependency Verification ──
        missing = []
        try:
            from automation.dependency_guard import check_dependencies, ensure_all

            ensure_all()
            missing = check_dependencies()
            if missing:
                self._startup_statuses["Dependency Verification"] = "SKIPPED"
                s_logger.warning(
                    "PHASE 2: Dependency Verification -> SKIPPED (missing: %s)",
                    [x[1] for x in missing],
                )
            else:
                self._startup_statuses["Dependency Verification"] = "SUCCESS"
                s_logger.info("PHASE 2: Dependency Verification -> SUCCESS")
        except Exception as e:
            self._startup_statuses["Dependency Verification"] = "FAILED"
            s_logger.error("PHASE 2: Dependency Verification -> FAILED: %s", e)

        if missing:
            # Wire dependency check screen if packages are missing
            self._build_dependency_screen(missing)
        else:
            self._build_normal_app()

    def _build_normal_app(self) -> None:
        """Sets up the normal app layout, registers pages, and kicks off async init."""
        from core.logger import get_logger

        s_logger = get_logger("Startup")

        # ── Phase 6: GUI Layout ──
        try:
            self._build_normal_app_layout()
            self._startup_statuses["GUI"] = "SUCCESS"
            s_logger.info("PHASE 6: GUI -> SUCCESS")
        except Exception as e:
            self._startup_statuses["GUI"] = "FAILED"
            s_logger.critical("PHASE 6: GUI -> FAILED: %s", e)
            raise

        # ── Phase 7: Page Registration ──
        try:
            self._build_pages()
            self._startup_statuses["Page Registration"] = "SUCCESS"
            s_logger.info("PHASE 7: Page Registration -> SUCCESS")
        except Exception as e:
            self._startup_statuses["Page Registration"] = "FAILED"
            s_logger.error("PHASE 7: Page Registration -> FAILED: %s", e)

        # ── Phase 8: Toolbar Binding ──
        try:
            self._build_toolbar(self._right_frame)
            self._startup_statuses["Toolbar Binding"] = "SUCCESS"
            s_logger.info("PHASE 8: Toolbar Binding -> SUCCESS")
        except Exception as e:
            self._startup_statuses["Toolbar Binding"] = "FAILED"
            s_logger.error("PHASE 8: Toolbar Binding -> FAILED: %s", e)

        # Navigate to default page
        self._navigate("dashboard")

        # Connect CAPTCHA handlers
        try:
            self._wire_captcha_handler()
        except Exception as e:
            s_logger.error("Failed to wire CAPTCHA handlers: %s", e)

        # Start async initialization thread
        self.run_async(self._initialize_app())

        # Check for onboarding after a short delay to allow services to init
        self.after(1000, self._check_onboarding)

    def _check_onboarding(self) -> None:
        """Check if first-time setup is required (no resume or empty profile)."""
        try:
            from services.form_service import get_form_service
            from services.resume_service import get_resume_service

            rs = get_resume_service()
            fs = get_form_service()
        except Exception:
            # Services not ready, retry
            self.after(500, self._check_onboarding)
            return

        needs_onboarding = False
        if not rs.exists or not fs.data.full_name or not fs.data.email:
            needs_onboarding = True

        if needs_onboarding:
            from gui.widgets.onboarding import OnboardingWizard

            def _on_complete(target_page: str | None):
                if target_page:
                    self._navigate(target_page)

            OnboardingWizard(self, _on_complete)

    async def _initialize_app(self) -> None:
        from automation.browser_manager import get_browser_manager
        from automation.vision_engine import get_vision_engine
        from core.database import get_database
        from core.logger import get_logger
        from services.form_service import get_form_service
        from services.profile_service import get_profile_service
        from services.queue_manager import get_job_queue_manager
        from services.resume_service import get_resume_service

        logger = get_logger("StartupAsync")
        logger.info("============================================================")
        logger.info("   Executing Phased Startup Sequence (Asynchronous Phases)")
        logger.info("============================================================")

        # ── Phase 3: Database ──
        try:
            db = get_database()
            await db.initialize()
            self._startup_statuses["Database"] = "SUCCESS"
            logger.info("PHASE 3: Database -> SUCCESS")

            # Database initialized: Refresh all active pages to load real DB metrics
            self._refresh_all_loaded_pages()
        except Exception as e:
            self._startup_statuses["Database"] = "FAILED"
            logger.error("PHASE 3: Database -> FAILED: %s", e)

        # ── Phase 4: Services ──
        try:
            get_form_service()
            get_resume_service()
            get_profile_service()
            get_job_queue_manager()
            self._startup_statuses["Services"] = "SUCCESS"
            logger.info("PHASE 4: Services -> SUCCESS")
        except Exception as e:
            self._startup_statuses["Services"] = "FAILED"
            logger.error("PHASE 4: Services -> FAILED: %s", e)

        # ── Phase 5: Browser ──
        try:
            get_browser_manager()
            get_vision_engine()
            self._startup_statuses["Browser"] = "SUCCESS"
            logger.info("PHASE 5: Browser -> SUCCESS")
        except Exception as e:
            self._startup_statuses["Browser"] = "FAILED"
            logger.error("PHASE 5: Browser -> FAILED: %s", e)

        # Register state dispatcher
        try:
            from services.state_manager import get_state_manager

            get_state_manager().set_dispatcher(self.after)
        except Exception as e:
            logger.error("Failed to register state manager dispatcher: %s", e)

        # ── Phase 9: Scheduler ──
        try:
            from services.scheduler_service import get_scheduler, set_app_loop

            set_app_loop(self._loop)
            scheduler = get_scheduler()
            scheduler.start()
            scheduler.apply_interval(self._settings.scheduler_interval)

            # Start browser health monitor
            from automation.browser_health import get_health_monitor

            get_health_monitor().start()

            self._startup_statuses["Scheduler"] = "SUCCESS"
            logger.info("PHASE 9: Scheduler -> SUCCESS")
        except Exception as e:
            self._startup_statuses["Scheduler"] = "FAILED"
            logger.error("PHASE 9: Scheduler -> FAILED: %s", e)

        # Start telemetry loop
        try:
            self.run_async(self._telemetry_monitor_loop())
        except Exception as e:
            logger.error("Failed to start telemetry loop: %s", e)

        # ── Phase 10: Application Ready ──
        self._startup_statuses["Application Ready"] = "SUCCESS"
        logger.info("PHASE 10: Application Ready -> SUCCESS. Startup Completed.")

    # ── Page management ───────────────────────────────────────────────────────

    def _refresh_all_loaded_pages(self) -> None:
        """Call refresh() on all successfully built pages that have it, on the main thread."""

        def _refresh():
            for key, page in self._pages.items():
                if not isinstance(page, PlaceholderPage) and hasattr(page, "refresh"):
                    try:
                        page.refresh()
                    except Exception as e:
                        from core.logger import get_logger

                        get_logger("App").error(
                            "Failed to refresh page %s after database initialization: %s",
                            key,
                            e,
                        )

        self.after(0, _refresh)

    def _retry_load_page(self, page_key: str) -> None:
        """Re-attempt constructing a page that previously failed to initialize."""
        page_classes = {
            "dashboard": DashboardPage,
            "jobs": JobsPage,
            "linkedin_easy_apply": LinkedinEasyApplyPage,
            "queue": QueuePage,
            "applications": ApplicationsPage,
            "browser": BrowserPage,
            "ai": AIPage,
            "resume": ResumePage,
            "profile": ProfilePage,
            "scheduler": SchedulerPage,
            "analytics": AnalyticsPage,
            "settings": SettingsPage,
            "logs": LogsViewerPage,
            "diagnostics": DiagnosticsPage,
            "dependencies": DependenciesPage,
        }
        if page_key not in page_classes:
            return

        cls = page_classes[page_key]
        try:
            if page_key in self._pages:
                try:
                    self._pages[page_key].destroy()
                except Exception as _exc:
                    logger.debug("Suppressed: %s", _exc)
            page = cls(self._content, app=self)
            page.grid(row=0, column=0, sticky="nsew")
            self._pages[page_key] = page

            # If current page, display it
            if self._current_page == page_key:
                page.grid()
                page.lift()
                if hasattr(page, "on_show"):
                    page.on_show()
            from core.logger import get_logger

            get_logger("App").info(
                "Successfully loaded and registered page: %s", page_key
            )
        except Exception as exc:
            import traceback

            tb = traceback.format_exc()
            from core.logger import get_logger

            get_logger("App").error(
                "Failed to reload page %s: %s\n%s", page_key, exc, tb
            )

    def _build_pages(self) -> None:
        page_classes = {
            "dashboard": DashboardPage,
            "jobs": JobsPage,
            "linkedin_easy_apply": LinkedinEasyApplyPage,
            "queue": QueuePage,
            "applications": ApplicationsPage,
            "browser": BrowserPage,
            "ai": AIPage,
            "resume": ResumePage,
            "profile": ProfilePage,
            "scheduler": SchedulerPage,
            "analytics": AnalyticsPage,
            "settings": SettingsPage,
            "logs": LogsViewerPage,
            "diagnostics": DiagnosticsPage,
            "dependencies": DependenciesPage,
        }
        for key, cls in page_classes.items():
            try:
                page = cls(self._content, app=self)
                page.grid(row=0, column=0, sticky="nsew")
                self._pages[key] = page
            except Exception as e:
                import traceback

                from core.logger import get_logger

                tb = traceback.format_exc()
                get_logger("App").error(
                    "Failed to construct page '%s': %s\n%s", key, e, tb
                )

                # Register PlaceholderPage
                placeholder = PlaceholderPage(
                    self._content, app=self, page_name=key, error_msg=str(e)
                )
                placeholder.grid(row=0, column=0, sticky="nsew")
                self._pages[key] = placeholder

    def _navigate(self, page_key: str) -> None:
        if page_key not in self._pages:
            return

        # Hide current
        if self._current_page and self._current_page in self._pages:
            current_page_frame = self._pages[self._current_page]
            if current_page_frame.winfo_exists():
                current_page_frame.grid_remove()
                if hasattr(current_page_frame, "on_hide"):
                    current_page_frame.on_hide()

        # Show new
        page = self._pages[page_key]
        page.grid()
        page.lift()
        self._current_page = page_key
        self._sidebar.set_active(page_key)

        # Call on_show hook if defined
        if hasattr(page, "on_show"):
            page.on_show()

    # ── CAPTCHA handler wiring ────────────────────────────────────────────────

    def _wire_captcha_handler(self) -> None:
        from automation.captcha_handler import get_captcha_handler
        from gui.widgets.dialogs import CaptchaDialog, LoginDialog, OTPDialog

        handler = get_captcha_handler()

        def on_captcha(url: str) -> None:
            self.after(
                0, lambda: CaptchaDialog(self, url, on_resume=handler.resolve_captcha)
            )

        def on_otp() -> None:
            self.after(0, lambda: OTPDialog(self, on_submit=handler.resolve_otp))

        def on_login() -> None:
            self.after(
                0,
                lambda: LoginDialog(
                    self, source="Job Site", on_done=handler.resolve_login
                ),
            )

        handler.on_captcha_detected = on_captcha
        handler.on_otp_detected = on_otp
        handler.on_login_detected = on_login

    # ── Top Toolbar ───────────────────────────────────────────────────────────

    def _build_toolbar(self, parent: ctk.CTkFrame) -> None:
        from core.logger import get_logger

        get_logger("TopToolbar")

        toolbar = ctk.CTkFrame(
            parent,
            height=50,
            fg_color=COLORS["bg_secondary"],
            corner_radius=0,
            border_width=1,
            border_color=COLORS["border"],
        )
        toolbar.grid(row=0, column=0, sticky="ew", padx=0, pady=0)
        toolbar.grid_propagate(False)

        btn_frame = ctk.CTkFrame(toolbar, fg_color="transparent")
        btn_frame.pack(side="left", padx=10, fill="y")

        def create_tool_btn(icon, text, cmd, fg=None, hover=None):
            btn = ctk.CTkButton(
                btn_frame,
                text=f"{icon} {text}",
                font=FONTS["body_sm"],
                height=32,
                corner_radius=6,
                command=cmd,
            )
            if fg:
                btn.configure(fg_color=fg)
            else:
                btn.configure(
                    fg_color=COLORS["bg_card"],
                    hover_color=COLORS["bg_hover"],
                    text_color=COLORS["text_primary"],
                )
            if hover:
                btn.configure(hover_color=hover)
            btn.pack(side="left", padx=4, pady=9)
            return btn

        create_tool_btn("🔍", "Search Jobs", self._tb_search_jobs)
        create_tool_btn(
            "⚡",
            "Start Auto Apply",
            self._tb_start_apply,
            fg="#1F85DE",
            hover="#196BAE",
        )
        self._btn_pause = create_tool_btn("⏸️", "Pause", self._tb_pause)
        self._btn_resume = create_tool_btn("▶️", "Resume", self._tb_resume)
        create_tool_btn(
            "🛑",
            "Emergency Stop",
            self._tb_emergency_stop,
            fg=COLORS["accent_red"],
            hover="#B02A2A",
        )
        create_tool_btn("🔄", "Retry Failed", self._tb_retry_failed)
        create_tool_btn("📥", "Import Links", self._tb_import_links)
        create_tool_btn("📤", "Export", self._tb_export)
        create_tool_btn("↻", "Refresh", self._tb_refresh)

    def _tb_search_jobs(self):
        self._navigate("jobs")
        page = self._pages["jobs"]
        if hasattr(page, "start_search_flow"):
            page.start_search_flow()

    def _tb_start_apply(self):
        from services.queue_manager import get_application_queue

        async def run():
            q = get_application_queue()
            await q.apply_all()
            await q.start_processing()

        self.run_async(run())
        self._navigate("queue")

    def _tb_pause(self):
        from services.queue_manager import get_application_queue

        get_application_queue().pause()

    def _tb_resume(self):
        from services.queue_manager import get_application_queue

        self.run_async(get_application_queue().resume())

    def _tb_emergency_stop(self):
        from automation.browser_manager import get_browser_manager
        from services.queue_manager import get_application_queue

        self.run_async(get_application_queue().stop_processing())
        get_application_queue().pause()

        async def close_browser():
            try:
                bm = get_browser_manager()
                await bm.close_browser()
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

        self.run_async(close_browser())
        from core.logger import get_logger

        get_logger("TopToolbar").info(
            "Emergency Stop triggered: stopped queue, killed browser context."
        )

    def _tb_retry_failed(self):
        from services.queue_manager import get_application_queue

        self.run_async(get_application_queue().retry_failed())

    def _tb_import_links(self):
        from gui.widgets.dialogs import ImportLinksDialog

        ImportLinksDialog(self)

    def _tb_export(self):
        from services.job_service import get_job_service

        async def do_export():
            try:
                js = get_job_service()
                j_csv, a_csv = await js.export_csv()
                from core.logger import get_logger

                get_logger("TopToolbar").info(
                    "Exported CSV successfully. Jobs: %s, Applied: %s", j_csv, a_csv
                )
            except Exception as e:
                from core.logger import get_logger

                get_logger("TopToolbar").error("Export failed: %s", e)

        self.run_async(do_export())

    def _tb_refresh(self):
        self._navigate(self._current_page or "dashboard")

    # ── Close ─────────────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        # 1. Stop scheduler
        try:
            from services.scheduler_service import get_scheduler

            get_scheduler().stop()
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)

        # 2. Stop health monitor
        try:
            from automation.browser_health import get_health_monitor

            get_health_monitor().stop()
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)

        # 3. Close database connection
        async def _close_db():
            try:
                from core.database import get_database

                await get_database().close()
            except Exception as _exc:
                logger.debug("Suppressed: %s", _exc)

        import asyncio

        if self._loop.is_running():
            asyncio.run_coroutine_threadsafe(_close_db(), self._loop).result(timeout=3)

        # 4. Stop the async loop and destroy the window
        self._loop.call_soon_threadsafe(self._loop.stop)
        self.destroy()

    # ── Dependency Prompt Screen ──────────────────────────────────────────────

    def _build_dependency_screen(self, missing) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        from gui.pages.installer_screen import InstallerScreen

        def on_complete():
            for child in self.winfo_children():
                child.destroy()
            from automation.dependency_guard import ensure_all

            ensure_all()
            self._build_normal_app()

        screen = InstallerScreen(self, missing_packages=missing, on_complete=on_complete)
        screen.grid(row=0, column=0, sticky="nsew")

    # ── Normal App UI Setup ───────────────────────────────────────────────────

    def _build_normal_app_layout(self) -> None:
        # Reset grid weights
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Sidebar
        self._sidebar = Sidebar(self, on_navigate=self._navigate)
        self._sidebar.grid(row=0, column=0, sticky="nsew")

        # Right frame containing Top Toolbar and page content
        self._right_frame = ctk.CTkFrame(
            self, fg_color=COLORS["bg_primary"], corner_radius=0
        )
        self._right_frame.grid(row=0, column=1, sticky="nsew")
        self._right_frame.grid_columnconfigure(0, weight=1)
        self._right_frame.grid_rowconfigure(
            1, weight=1
        )  # Row 0 is toolbar, Row 1 is pages

        # Content area (for pages)
        self._content = ctk.CTkFrame(
            self._right_frame, fg_color=COLORS["bg_primary"], corner_radius=0
        )
        self._content.grid(row=1, column=0, sticky="nsew")
        self._content.grid_columnconfigure(0, weight=1)
        self._content.grid_rowconfigure(0, weight=1)

    # ── Background Telemetry Loop ─────────────────────────────────────────────

    async def _telemetry_monitor_loop(self) -> None:
        import re

        import psutil

        from automation.browser_session_pool import get_browser_session_pool
        from core.logger import get_logger
        from services.session_manager import get_session_manager
        from services.state_manager import get_state_manager

        t_logger = get_logger("TelemetryMonitor")
        stm = get_state_manager()
        sm = get_session_manager()
        pool = get_browser_session_pool()

        while True:
            try:
                # 1. CPU & RAM
                cpu = "Unavailable"
                mem = "Unavailable"
                try:
                    cpu = f"{psutil.cpu_percent()}%"
                    mem = f"{psutil.virtual_memory().percent}%"
                except Exception as _exc:
                    logger.debug("Suppressed: %s", _exc)

                # 2. GPU Active
                gpu = "Unavailable"
                try:
                    import subprocess

                    res = subprocess.run(
                        ["nvidia-smi"], capture_output=True, text=True, timeout=2
                    )
                    if res.returncode == 0:
                        gpu = "Active"
                        m = re.search(
                            r"GeForce\s+[^\n]+|RTX\s+[^\n]+|NVIDIA\s+[^\n]+", res.stdout
                        )
                        if m:
                            gpu = f"Active ({m.group(0).split('...')[0].strip()})"
                    else:
                        gpu = "Unavailable"
                except Exception:
                    gpu = "Unavailable"

                # 3. Brave browser PID & memory
                conn_status = sm.get_connection_status()
                brave_pid = "Unavailable"
                brave_mem = "Unavailable"

                if "Connected" in conn_status:
                    try:
                        for p in psutil.process_iter(["pid", "name"]):
                            if p.info["name"] and any(
                                x in p.info["name"].lower() for x in ["brave", "chrome"]
                            ):
                                brave_pid = str(p.info["pid"])
                                mem_mb = p.memory_info().rss / (1024 * 1024)
                                brave_mem = f"~{int(mem_mb)} MB"
                                break
                    except Exception as _exc:
                        logger.debug("Suppressed: %s", _exc)

                # 4. Browser active page details
                current_url = "Unavailable"
                current_tab = "Unavailable"
                cookies_count = 0
                if pool.is_healthy:
                    try:
                        ctx = await pool.get_context()
                        pages = ctx.pages
                        if pages:
                            page = pages[0]
                            current_url = page.url
                            current_tab = await page.title()
                            cookies = await ctx.cookies()
                            cookies_count = len(cookies)
                    except Exception as _exc:
                        logger.debug("Suppressed: %s", _exc)

                # Update StateManager
                stm.update_state(
                    browser_status=conn_status,
                    current_url=current_url,
                    current_tab=current_tab,
                    cookies_count=cookies_count,
                    live_progress_text=f"{brave_pid}|{brave_mem}|{cpu}|{mem}|{gpu}",
                )

            except Exception as e:
                t_logger.error("Telemetry monitor error: %s", e)

            await asyncio.sleep(5.0)
