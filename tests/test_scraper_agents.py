"""Unit tests for scraper agents — no browser, no API calls."""

import sqlite3

from src.agents.scraper import create_scraper
from src.agents.scraper.base import PLAYWRIGHT_MCP_CONFIG, BaseScraper
from src.agents.scraper.blinkit import BlinkitScraper
from src.agents.scraper.instamart import InstamartScraper
from src.agents.scraper.zepto import ZeptoScraper
from src.config.settings import settings
from src.models.product import Platform


class TestBaseScraper:
    def test_mcp_config(self, db_session: sqlite3.Connection) -> None:
        scraper = BlinkitScraper(db_session)
        opts = scraper.get_agent_options()
        assert "playwright" in opts["mcp_servers"]
        assert opts["mcp_servers"]["playwright"] == PLAYWRIGHT_MCP_CONFIG

    def test_model_selection(self, db_session: sqlite3.Connection) -> None:
        scraper = BlinkitScraper(db_session)
        opts = scraper.get_agent_options()
        assert opts["model"] == settings.scraper_model

    def test_agent_options_structure(self, db_session: sqlite3.Connection) -> None:
        scraper = BlinkitScraper(db_session)
        opts = scraper.get_agent_options()
        assert "system_prompt" in opts
        assert "max_turns" in opts
        assert "max_budget_usd" in opts
        assert "allowed_tools" in opts
        assert "permission_mode" in opts
        assert opts["max_budget_usd"] == settings.max_budget_scraper

    def test_service_initialized(self, db_session: sqlite3.Connection) -> None:
        scraper = BlinkitScraper(db_session)
        assert scraper.service is not None
        assert scraper.conn is db_session


class TestBlinkitScraper:
    def test_platform(self, db_session: sqlite3.Connection) -> None:
        scraper = BlinkitScraper(db_session)
        assert scraper.platform == Platform.BLINKIT

    def test_prompt_contains_lat_lon(self, db_session: sqlite3.Connection) -> None:
        scraper = BlinkitScraper(db_session)
        prompt = scraper.get_system_prompt()
        assert "lat" in prompt
        assert "lon" in prompt

    def test_prompt_contains_xhr_details(self, db_session: sqlite3.Connection) -> None:
        scraper = BlinkitScraper(db_session)
        prompt = scraper.get_system_prompt()
        assert "XHR" in prompt
        assert "listing" in prompt

    def test_url_pattern(self, db_session: sqlite3.Connection) -> None:
        scraper = BlinkitScraper(db_session)
        url = scraper.get_scrape_url("122001", "Dairy & Bread")
        assert "blinkit.com" in url
        assert "lat=" in url
        assert "lon=" in url
        assert "dairy-bread" in url

    def test_url_with_known_pincode(self, db_session: sqlite3.Connection) -> None:
        scraper = BlinkitScraper(db_session)
        url = scraper.get_scrape_url("122001", "Dairy & Bread")
        assert "28.4595" in url
        assert "77.0266" in url


class TestZeptoScraper:
    def test_platform(self, db_session: sqlite3.Connection) -> None:
        scraper = ZeptoScraper(db_session)
        assert scraper.platform == Platform.ZEPTO

    def test_prompt_contains_store_id(self, db_session: sqlite3.Connection) -> None:
        scraper = ZeptoScraper(db_session)
        prompt = scraper.get_system_prompt()
        assert "store_id" in prompt

    def test_url_pattern(self, db_session: sqlite3.Connection) -> None:
        scraper = ZeptoScraper(db_session)
        url = scraper.get_scrape_url("122001", "Dairy & Bread")
        assert "zepto.co" in url
        assert "pincode=122001" in url
        assert "dairy-bread" in url


class TestInstamartScraper:
    def test_platform(self, db_session: sqlite3.Connection) -> None:
        scraper = InstamartScraper(db_session)
        assert scraper.platform == Platform.INSTAMART

    def test_prompt_contains_tid(self, db_session: sqlite3.Connection) -> None:
        scraper = InstamartScraper(db_session)
        prompt = scraper.get_system_prompt()
        assert "tid" in prompt

    def test_url_pattern(self, db_session: sqlite3.Connection) -> None:
        scraper = InstamartScraper(db_session)
        url = scraper.get_scrape_url("122001", "Dairy & Bread")
        assert "swiggy.com" in url
        assert "pincode=122001" in url
        assert "dairy-bread" in url


class TestScraperFactory:
    def test_create_blinkit(self, db_session: sqlite3.Connection) -> None:
        scraper = create_scraper(Platform.BLINKIT, db_session)
        assert isinstance(scraper, BlinkitScraper)

    def test_create_zepto(self, db_session: sqlite3.Connection) -> None:
        scraper = create_scraper(Platform.ZEPTO, db_session)
        assert isinstance(scraper, ZeptoScraper)

    def test_create_instamart(self, db_session: sqlite3.Connection) -> None:
        scraper = create_scraper(Platform.INSTAMART, db_session)
        assert isinstance(scraper, InstamartScraper)

    def test_create_returns_base_scraper(self, db_session: sqlite3.Connection) -> None:
        for platform in Platform:
            scraper = create_scraper(platform, db_session)
            assert isinstance(scraper, BaseScraper)

    def test_create_invalid_platform(self, db_session: sqlite3.Connection) -> None:
        import pytest

        with pytest.raises(ValueError, match="Unknown platform"):
            create_scraper("invalid", db_session)
