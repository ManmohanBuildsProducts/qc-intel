"""Base scraper agent — abstract class using Claude Agent SDK with Playwright MCP."""

import logging
import sqlite3
from abc import ABC, abstractmethod

from src.config.settings import settings
from src.models.product import Platform, ScrapeRun, TimeOfDay

from .service import ScrapeService

logger = logging.getLogger(__name__)

PLAYWRIGHT_MCP_CONFIG = {
    "command": "npx",
    "args": ["@anthropic-ai/mcp-playwright@latest"],
}


class BaseScraper(ABC):
    """Abstract base for platform-specific scraper agents."""

    def __init__(self, platform: Platform, conn: sqlite3.Connection) -> None:
        self.platform = platform
        self.conn = conn
        self.service = ScrapeService(conn)

    @abstractmethod
    def get_system_prompt(self) -> str:
        """Return the platform-specific system prompt for the Claude agent."""

    @abstractmethod
    def get_scrape_url(self, pincode: str, category: str) -> str:
        """Return the URL to scrape for a given pincode and category."""

    def get_agent_options(self) -> dict:
        """Build the ClaudeAgentOptions kwargs for this scraper."""
        return {
            "model": settings.scraper_model,
            "system_prompt": self.get_system_prompt(),
            "max_turns": 10,
            "max_budget_usd": settings.max_budget_scraper,
            "mcp_servers": {"playwright": PLAYWRIGHT_MCP_CONFIG},
            "allowed_tools": [
                "mcp__playwright__browser_navigate",
                "mcp__playwright__browser_network_requests",
                "mcp__playwright__browser_snapshot",
                "mcp__playwright__browser_wait_for",
                "mcp__playwright__browser_evaluate",
                "mcp__playwright__browser_click",
            ],
            "permission_mode": "bypassPermissions",
        }

    async def scrape(self, pincode: str, category: str, time_of_day: TimeOfDay) -> ScrapeRun:
        """Run the agent: navigate, intercept XHR, parse, persist."""
        from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

        url = self.get_scrape_url(pincode, category)
        agent_opts = self.get_agent_options()

        prompt = (
            f"Navigate to {url} and intercept the API responses containing product data. "
            f"Extract the product JSON array from the XHR responses. "
            f"Return ONLY the raw JSON array of products, no other text."
        )

        raw_json = None
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                **agent_opts,
                allow_dangerously_skip_permissions=True,
            ),
        ):
            if isinstance(message, ResultMessage):
                raw_json = message.result

        if not raw_json:
            from src.models.exceptions import ScrapeError

            raise ScrapeError(self.platform.value, "Agent returned no data")

        import json

        try:
            items = json.loads(raw_json)
        except json.JSONDecodeError as e:
            from src.models.exceptions import ScrapeError

            raise ScrapeError(self.platform.value, f"Invalid JSON from agent: {e}") from e

        return self.service.process_scrape_results(items, self.platform, pincode, category, time_of_day)
