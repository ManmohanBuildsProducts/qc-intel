"""Base scraper — deterministic Playwright MCP scraping, no LLM in the loop."""

import json
import logging
import sqlite3
from abc import ABC, abstractmethod

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.models.product import Platform, ScrapeRun, TimeOfDay

from .service import ScrapeService

logger = logging.getLogger(__name__)

PLAYWRIGHT_SERVER = StdioServerParameters(
    command="npx",
    args=["@playwright/mcp@latest"],
)

ALLOWED_TOOLS = {
    "browser_navigate",
    "browser_network_requests",
    "browser_snapshot",
    "browser_wait_for",
    "browser_evaluate",
    "browser_click",
    "browser_close",
}


class BaseScraper(ABC):
    """Abstract base for platform-specific scrapers using Playwright MCP."""

    def __init__(self, platform: Platform, conn: sqlite3.Connection) -> None:
        self.platform = platform
        self.conn = conn
        self.service = ScrapeService(conn)

    @abstractmethod
    def get_system_prompt(self) -> str:
        """Return the platform-specific system prompt (kept for tests/docs)."""

    @abstractmethod
    def get_scrape_url(self, pincode: str, category: str) -> str:
        """Return the URL to scrape for a given pincode and category."""

    @abstractmethod
    async def _run_scrape(self, session: ClientSession, pincode: str, category: str) -> list[dict]:
        """Platform-specific scraping logic. Returns list of product dicts."""

    async def scrape(self, pincode: str, category: str, time_of_day: TimeOfDay) -> ScrapeRun:
        """Run the scraper: open browser, extract products, persist."""
        async with stdio_client(PLAYWRIGHT_SERVER) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                try:
                    items = await self._run_scrape(session, pincode, category)
                finally:
                    try:
                        await session.call_tool("browser_close", {})
                    except Exception:
                        pass

        if not items:
            from src.models.exceptions import ScrapeError
            raise ScrapeError(self.platform.value, "Scraper returned no products")

        logger.info("[%s] Scraped %d products for %s/%s", self.platform.value, len(items), pincode, category)
        return self.service.process_scrape_results(items, self.platform, pincode, category, time_of_day)

    # --- Helpers for subclasses ---

    async def _navigate(self, session: ClientSession, url: str) -> str:
        """Navigate and return the result text."""
        result = await session.call_tool("browser_navigate", {"url": url})
        return self._result_text(result)

    async def _evaluate(self, session: ClientSession, js_function: str) -> str:
        """Run a JS function in the browser and return the result text."""
        result = await session.call_tool("browser_evaluate", {"function": js_function})
        return self._result_text(result)

    async def _wait(self, session: ClientSession, state: str = "networkidle", timeout: int = 10000) -> None:
        """Wait for a browser state."""
        try:
            await session.call_tool("browser_wait_for", {"time": min(timeout, 5000)})
        except Exception:
            pass

    async def _snapshot(self, session: ClientSession) -> str:
        """Get page accessibility snapshot."""
        result = await session.call_tool("browser_snapshot", {})
        return self._result_text(result)

    @staticmethod
    def _result_text(result) -> str:
        """Extract text from MCP tool result."""
        text = ""
        for content in result.content:
            if hasattr(content, "text"):
                text += content.text
        return text

    @staticmethod
    def _parse_json_from_evaluate(text: str) -> list | dict | None:
        """Parse JSON from browser_evaluate result text."""
        # The MCP result wraps the value in a "### Result" block
        import re

        # Look for the JSON between ### Result and next ###
        match = re.search(r"### Result\s*\n(.*?)(?:\n###|\Z)", text, re.DOTALL)
        if match:
            raw = match.group(1).strip()
            # Remove wrapping quotes if present
            if raw.startswith('"') and raw.endswith('"'):
                try:
                    raw = json.loads(raw)  # Unescape the string
                except json.JSONDecodeError:
                    pass
            if isinstance(raw, str):
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    pass
            else:
                return raw

        # Fallback: try to find any JSON array in the text
        bracket_start = text.find("[")
        if bracket_start >= 0:
            depth = 0
            for i in range(bracket_start, len(text)):
                if text[i] == "[":
                    depth += 1
                elif text[i] == "]":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[bracket_start : i + 1])
                        except json.JSONDecodeError:
                            pass
                        break
        return None
