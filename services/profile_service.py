"""
Profile service — provides candidate profile details by delegating to form service.
"""

from __future__ import annotations

from core.logger import get_logger

logger = get_logger(__name__)

from core.models import FormData
from services.form_service import get_form_service


class ProfileService:
    def __init__(self) -> None:
        pass

    async def get_profile(self) -> FormData:
        """Return the parsed candidate profile FormData model."""
        form_svc = get_form_service()
        return form_svc.data


_profile_service: ProfileService | None = None


def get_profile_service() -> ProfileService:
    global _profile_service
    if _profile_service is None:
        _profile_service = ProfileService()

        # Register in central service registry
        try:
            from core.service_registry import ServiceRegistry

            ServiceRegistry.register("ProfileService", _profile_service)
        except Exception as _exc:
            logger.debug("Suppressed: %s", _exc)

    return _profile_service
