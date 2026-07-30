"""
Base scraper class with shared parsing utilities.
All scrapers extend this.
"""

from __future__ import annotations

from playwright.async_api import Page

from core.logger import get_logger
from core.models import Job

logger = get_logger(__name__)


class BaseScraper:
    """
    Base class for all job site scrapers.
    """

    SOURCE: str = "Unknown"

    async def scrape_playwright(
        self,
        page: Page,
        keyword: str,
        location: str,
    ) -> list[Job]:
        raise NotImplementedError
