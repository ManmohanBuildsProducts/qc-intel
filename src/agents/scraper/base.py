"""Base scraper — deterministic Playwright MCP scraping, no LLM in the loop."""

import asyncio
import json
import logging
import os
import sqlite3
from abc import ABC, abstractmethod

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.models.product import Platform, ScrapeRun, TimeOfDay

from .service import ScrapeService

logger = logging.getLogger(__name__)

# Retry config: 3 attempts with exponential backoff (2s, 4s, 8s)
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 2


def _stealth_script_path() -> str:
    """Return absolute path to the stealth init script."""
    return os.path.join(os.path.dirname(__file__), "stealth.js")


def _get_proxy_url(platform: Platform | None = None) -> str | None:
    """Get proxy URL for a platform, falling back to global QC_PROXY_URL.

    Per-platform proxy config:
    - Blinkit (Cloudflare): QC_PROXY_URL_BLINKIT
    - Zepto (Akamai Bot Manager): QC_PROXY_URL_ZEPTO
    - Instamart (AWS WAF): QC_PROXY_URL_INSTAMART
    """
    if platform:
        platform_var = f"QC_PROXY_URL_{platform.value.upper()}"
        platform_proxy = os.environ.get(platform_var)
        if platform_proxy:
            return platform_proxy
    return os.environ.get("QC_PROXY_URL")


def _playwright_server(
    extra_args: list[str] | None = None,
    platform: Platform | None = None,
) -> StdioServerParameters:
    """Build Playwright MCP server params with stealth, proxy, and browser config.

    Browser selection:
    - Blinkit → Chromium (avoids Firefox profile lock when running parallel with Zepto)
    - Zepto → Firefox (default, best stealth)
    - Instamart → overrides to Chromium in its own _scrape_once()
    """
    args = ["@playwright/mcp@latest", "--browser", "firefox", "--headless", "--isolated"]
    # Stealth: patch navigator.webdriver, plugins, WebGL, etc. before page loads
    stealth_path = _stealth_script_path()
    if os.path.exists(stealth_path):
        args += ["--init-script", stealth_path]
        logger.debug("[base] Stealth init script: %s", stealth_path)
    proxy_url = _get_proxy_url(platform)
    if proxy_url:
        args += ["--proxy-server", proxy_url]
        logger.info("[base] Using proxy for %s: %s", platform.value if platform else "global", proxy_url)
    if extra_args:
        args += extra_args
    return StdioServerParameters(command="npx", args=args)


PLAYWRIGHT_SERVER = StdioServerParameters(
    command="npx",
    args=["@playwright/mcp@latest", "--browser", "firefox", "--headless"],
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
        """Run the scraper with exponential backoff retry for transient failures.

        Retries up to MAX_RETRIES times with delays of 2s, 4s, 8s.
        Only retries on transient errors (connection, timeout, empty results).
        """
        last_error: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                items = await self._scrape_once(pincode, category)

                if not items:
                    if attempt < MAX_RETRIES:
                        delay = BACKOFF_BASE_SECONDS ** attempt
                        logger.warning(
                            "[%s] Empty results on attempt %d/%d, retrying in %ds...",
                            self.platform.value, attempt, MAX_RETRIES, delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                    from src.models.exceptions import ScrapeError
                    raise ScrapeError(self.platform.value, "Scraper returned no products after retries")

                logger.info(
                    "[%s] Scraped %d products for %s/%s (attempt %d)",
                    self.platform.value, len(items), pincode, category, attempt,
                )
                return self.service.process_scrape_results(items, self.platform, pincode, category, time_of_day)

            except Exception as e:
                last_error = e
                # Don't retry on non-transient errors (config, auth, etc.)
                from src.models.exceptions import ScrapeError
                if attempt >= MAX_RETRIES:
                    raise
                delay = BACKOFF_BASE_SECONDS ** attempt
                logger.warning(
                    "[%s] Attempt %d/%d failed: %s. Retrying in %ds...",
                    self.platform.value, attempt, MAX_RETRIES, str(e)[:200], delay,
                )
                await asyncio.sleep(delay)

        # Should not reach here, but satisfy type checker
        raise last_error  # type: ignore[misc]

    async def _scrape_once(self, pincode: str, category: str) -> list[dict]:
        """Single scrape attempt: open browser, extract products."""
        async with stdio_client(_playwright_server(platform=self.platform)) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                try:
                    return await self._run_scrape(session, pincode, category)
                finally:
                    try:
                        await session.call_tool("browser_close", {})
                    except Exception:
                        pass

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
