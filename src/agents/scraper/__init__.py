"""Scraper agent layer — parsers, service, and platform-specific agents."""

import os
import sqlite3

from src.models.product import Platform

from .base import BaseScraper
from .blinkit import BlinkitScraper
from .blinkit_fast import BlinkitFastScraper
from .instamart import InstamartScraper
from .instamart_fast import InstamartFastScraper
from .parsers import parse_blinkit_products, parse_instamart_products, parse_zepto_products
from .service import ScrapeService
from .zepto import ZeptoScraper
from .zepto_fast import ZeptoFastScraper

__all__ = [
    "BaseScraper",
    "BlinkitFastScraper",
    "BlinkitScraper",
    "InstamartFastScraper",
    "InstamartScraper",
    "ScrapeService",
    "ZeptoFastScraper",
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


def create_scraper(platform: Platform, conn: sqlite3.Connection):
    """Factory: create the correct scraper for a given platform.

    Set QC_FAST_SCRAPE=1 to use XHR-intercepting fast scrapers for
    Zepto and Instamart (~10x faster, intercepts API JSON directly).
    """
    try:
        platform = Platform(platform)
    except ValueError:
        pass

    fast = os.environ.get("QC_FAST_SCRAPE")

    if fast:
        if platform == Platform.ZEPTO:
            return ZeptoFastScraper(conn)
        # Instamart fast scraper XHR interception not yet reliable — keep browser scraper
        # if platform == Platform.INSTAMART:
        #     return InstamartFastScraper(conn)

    if platform == Platform.BLINKIT and os.environ.get("QC_BLINKIT_FAST"):
        return BlinkitFastScraper(conn)

    scraper_cls = _SCRAPER_MAP.get(platform)
    if scraper_cls is None:
        msg = f"Unknown platform: {platform}"
        raise ValueError(msg)
    return scraper_cls(conn)
