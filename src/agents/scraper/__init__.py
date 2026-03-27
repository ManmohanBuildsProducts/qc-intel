"""Scraper agent layer — parsers, service, and platform-specific agents."""

import os
import sqlite3

from src.models.product import Platform

from .base import BaseScraper
from .blinkit import BlinkitScraper
from .blinkit_fast import BlinkitFastScraper
from .instamart import InstamartScraper
from .parsers import parse_blinkit_products, parse_instamart_products, parse_zepto_products
from .service import ScrapeService
from .zepto import ZeptoScraper

__all__ = [
    "BaseScraper",
    "BlinkitFastScraper",
    "BlinkitScraper",
    "InstamartScraper",
    "ScrapeService",
    "ZeptoScraper",
    "create_scraper",
    "parse_blinkit_products",
    "parse_instamart_products",
    "parse_zepto_products",
]

_SCRAPER_MAP: dict[Platform, type[BaseScraper]] = {
    Platform.BLINKIT: BlinkitScraper,
    Platform.ZEPTO: ZeptoScraper,
    Platform.INSTAMART: InstamartScraper,
}


def create_scraper(platform: Platform, conn: sqlite3.Connection) -> BaseScraper | BlinkitFastScraper:
    """Factory: create the correct scraper for a given platform.

    For Blinkit, uses the fast httpx-based scraper by default (set
    QC_BLINKIT_LEGACY=1 to use the browser-per-term scraper).
    """
    try:
        platform = Platform(platform)
    except ValueError:
        pass

    if platform == Platform.BLINKIT and os.environ.get("QC_BLINKIT_FAST"):
        return BlinkitFastScraper(conn)

    scraper_cls = _SCRAPER_MAP.get(platform)
    if scraper_cls is None:
        msg = f"Unknown platform: {platform}"
        raise ValueError(msg)
    return scraper_cls(conn)
