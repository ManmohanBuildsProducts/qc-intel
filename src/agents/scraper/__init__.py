"""Scraper agent layer — parsers, service, and platform-specific agents."""

import sqlite3

from src.models.product import Platform

from .base import BaseScraper
from .blinkit import BlinkitScraper
from .instamart import InstamartScraper
from .parsers import parse_blinkit_products, parse_instamart_products, parse_zepto_products
from .service import ScrapeService
from .zepto import ZeptoScraper

__all__ = [
    "BaseScraper",
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


def create_scraper(platform: Platform, conn: sqlite3.Connection) -> BaseScraper:
    """Factory: create the correct scraper for a given platform."""
    try:
        platform = Platform(platform)
    except ValueError:
        pass

    scraper_cls = _SCRAPER_MAP.get(platform)
    if scraper_cls is None:
        msg = f"Unknown platform: {platform}"
        raise ValueError(msg)
    return scraper_cls(conn)
