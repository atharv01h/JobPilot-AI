"""
Desktop notification service.
Current: plyer desktop notifications.
Architecture stubs for WhatsApp and email (future).
"""

from __future__ import annotations

import asyncio

from core.logger import get_logger

logger = get_logger(__name__)

try:
    from plyer import notification as _plyer_notify

    _PLYER_AVAILABLE = True
except Exception:
    _PLYER_AVAILABLE = False
    logger.warning("plyer not available — desktop notifications disabled")


class NotificationService:
    """Sends notifications via desktop (and future channels)."""

    def __init__(self, desktop_enabled: bool = True) -> None:
        self.desktop_enabled = desktop_enabled and _PLYER_AVAILABLE

    # ── Desktop ───────────────────────────────────────────────────────────────

    def notify_desktop(
        self,
        title: str,
        message: str,
        timeout: int = 8,
    ) -> None:
        if not self.desktop_enabled:
            logger.debug("Desktop notification skipped (disabled): %s", title)
            return
        try:
            _plyer_notify.notify(
                title=title,
                message=message,
                app_name="JobPilot AI",
                timeout=timeout,
            )
            logger.info("Desktop notification sent: %s", title)
        except Exception as exc:
            logger.warning("Desktop notification failed: %s", exc)

    async def notify_desktop_async(
        self, title: str, message: str, timeout: int = 8
    ) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, lambda: self.notify_desktop(title, message, timeout)
        )

    # ── Convenience methods ───────────────────────────────────────────────────

    def notify_jobs_found(self, count: int, source: str) -> None:
        self.notify_desktop(
            title="Jobs Found! 🎯",
            message=f"Found {count} new job(s) on {source}",
        )

    def notify_captcha(self, url: str) -> None:
        self.notify_desktop(
            title="⚠️  Human Verification Required",
            message=f"CAPTCHA detected. Please verify and click Resume.\n{url[:80]}",
            timeout=0,  # Persistent
        )

    def notify_applied(self, title: str, company: str) -> None:
        self.notify_desktop(
            title="Application Submitted ✅",
            message=f"Applied to: {title} at {company}",
        )

    def notify_error(self, context: str) -> None:
        self.notify_desktop(
            title="Error ❌",
            message=f"An error occurred: {context[:100]}",
        )

    # ── WhatsApp stub (future) ────────────────────────────────────────────────

    async def notify_whatsapp(self, message: str) -> None:
        """FUTURE: Send WhatsApp message via WhatsApp Business API."""
        logger.info("[WhatsApp STUB] %s", message)

    # ── Email stub (future) ───────────────────────────────────────────────────

    async def notify_email(self, subject: str, body: str) -> None:
        """FUTURE: Send email via SMTP."""
        logger.info("[Email STUB] %s: %s", subject, body[:60])


# ── Singleton ─────────────────────────────────────────────────────────────────

_notification_service: NotificationService | None = None


def get_notification_service() -> NotificationService:
    global _notification_service
    if _notification_service is None:
        from config.settings import get_settings

        settings = get_settings()
        _notification_service = NotificationService(
            desktop_enabled=settings.desktop_notifications_enabled
        )
    return _notification_service
