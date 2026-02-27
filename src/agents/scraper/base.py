"""Base scraper agent — abstract class using Gemini function calling with Playwright MCP."""

import json
import logging
import sqlite3
from abc import ABC, abstractmethod

from google import genai
from google.genai import types as genai_types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.config.settings import settings
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


def _json_schema_to_gemini(prop_def: dict) -> genai_types.Schema:
    """Convert a JSON Schema property definition to a Gemini Schema."""
    prop_type = prop_def.get("type", "string").upper()
    if prop_type not in {"STRING", "NUMBER", "INTEGER", "BOOLEAN", "ARRAY", "OBJECT"}:
        prop_type = "STRING"

    kwargs: dict = {
        "type": prop_type,
        "description": prop_def.get("description", ""),
    }

    # Handle array items
    if prop_type == "ARRAY" and "items" in prop_def:
        kwargs["items"] = _json_schema_to_gemini(prop_def["items"])

    # Handle object properties
    if prop_type == "OBJECT" and "properties" in prop_def:
        kwargs["properties"] = {
            k: _json_schema_to_gemini(v)
            for k, v in prop_def["properties"].items()
        }

    # Handle enum
    if "enum" in prop_def:
        kwargs["enum"] = prop_def["enum"]

    return genai_types.Schema(**kwargs)


def _mcp_tool_to_gemini(tool) -> genai_types.FunctionDeclaration:
    """Convert an MCP tool definition to a Gemini FunctionDeclaration."""
    properties = {}
    required = []
    schema = tool.inputSchema or {}
    for prop_name, prop_def in schema.get("properties", {}).items():
        properties[prop_name] = _json_schema_to_gemini(prop_def)
    if schema.get("required"):
        required = schema["required"]

    return genai_types.FunctionDeclaration(
        name=tool.name,
        description=tool.description or tool.name,
        parameters=genai_types.Schema(
            type="OBJECT",
            properties=properties,
            required=required,
        ),
    )


class BaseScraper(ABC):
    """Abstract base for platform-specific scraper agents."""

    def __init__(self, platform: Platform, conn: sqlite3.Connection) -> None:
        self.platform = platform
        self.conn = conn
        self.service = ScrapeService(conn)

    @abstractmethod
    def get_system_prompt(self) -> str:
        """Return the platform-specific system prompt for the agent."""

    @abstractmethod
    def get_scrape_url(self, pincode: str, category: str) -> str:
        """Return the URL to scrape for a given pincode and category."""

    @staticmethod
    def _extract_json_array(text: str) -> list | None:
        """Extract a JSON array from agent response text, handling markdown fences."""
        import re

        # Try direct parse
        text = text.strip()
        try:
            result = json.loads(text)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

        # Try extracting from markdown code fence
        fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
        if fence_match:
            try:
                result = json.loads(fence_match.group(1).strip())
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                pass

        # Try finding first [ ... ] block
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
                            result = json.loads(text[bracket_start : i + 1])
                            if isinstance(result, list):
                                return result
                        except json.JSONDecodeError:
                            pass
                        break

        return None

    async def scrape(self, pincode: str, category: str, time_of_day: TimeOfDay) -> ScrapeRun:
        """Run the agent: navigate, intercept XHR, parse, persist."""
        url = self.get_scrape_url(pincode, category)
        prompt = (
            f"Navigate to {url} and intercept the API responses containing product data.\n\n"
            f"Steps:\n"
            f"1. Use browser_navigate to open the URL\n"
            f"2. Use browser_wait_for to wait for network to be idle\n"
            f"3. Use browser_network_requests to capture all XHR/Fetch requests\n"
            f"4. Look for API responses containing product listing data\n"
            f"5. Use browser_evaluate to fetch the product data from the API endpoint directly\n\n"
            f"Return a JSON array where each object has these fields:\n"
            f"  id, name, brand, category, subcategory, unit, price, mrp, "
            f"available (boolean), max_allowed_quantity, image_url\n\n"
            f"Return ONLY the JSON array, no markdown fences, no explanation."
        )

        raw_json = await self._run_agent(prompt)

        if not raw_json:
            from src.models.exceptions import ScrapeError
            raise ScrapeError(self.platform.value, "Agent returned no data")

        # Try to extract JSON array from the response
        items = self._extract_json_array(raw_json)
        if items is None:
            from src.models.exceptions import ScrapeError
            logger.error("Agent response (first 2000 chars): %s", raw_json[:2000])
            raise ScrapeError(self.platform.value, "No JSON array found in agent response")

        return self.service.process_scrape_results(items, self.platform, pincode, category, time_of_day)

    async def _run_agent(self, prompt: str) -> str | None:
        """Run Gemini agent loop with Playwright MCP tools."""
        async with stdio_client(PLAYWRIGHT_SERVER) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Get MCP tools and filter to allowed set
                mcp_tools = await session.list_tools()
                filtered = [t for t in mcp_tools.tools if t.name in ALLOWED_TOOLS]
                tool_map = {t.name: t for t in filtered}

                # Convert to Gemini function declarations
                gemini_tools = [_mcp_tool_to_gemini(t) for t in filtered]

                client = genai.Client()
                messages = [genai_types.Content(role="user", parts=[genai_types.Part(text=prompt)])]

                for turn in range(settings.scrape_max_agent_turns):
                    response = await client.aio.models.generate_content(
                        model=settings.scraper_model,
                        contents=messages,
                        config=genai_types.GenerateContentConfig(
                            system_instruction=self.get_system_prompt(),
                            tools=[genai_types.Tool(function_declarations=gemini_tools)],
                        ),
                    )

                    # Check if model wants to call tools
                    candidate = response.candidates[0]
                    parts = candidate.content.parts

                    tool_calls = [p for p in parts if p.function_call]
                    if not tool_calls:
                        # Model returned text — we're done
                        text_parts = [p.text for p in parts if p.text]
                        return "\n".join(text_parts) if text_parts else None

                    # Append model response to messages
                    messages.append(candidate.content)

                    # Execute each tool call via MCP
                    tool_results = []
                    for part in tool_calls:
                        fc = part.function_call
                        logger.info("Tool call [%d]: %s", turn, fc.name)

                        if fc.name not in tool_map:
                            tool_results.append(genai_types.Part(
                                function_response=genai_types.FunctionResponse(
                                    name=fc.name,
                                    response={"error": f"Unknown tool: {fc.name}"},
                                )
                            ))
                            continue

                        try:
                            result = await session.call_tool(
                                fc.name,
                                arguments=dict(fc.args) if fc.args else {},
                            )
                            result_text = ""
                            for content in result.content:
                                if hasattr(content, "text"):
                                    result_text += content.text
                            tool_results.append(genai_types.Part(
                                function_response=genai_types.FunctionResponse(
                                    name=fc.name,
                                    response={"result": result_text[:8000]},
                                )
                            ))
                        except Exception as e:
                            logger.warning("Tool %s failed: %s", fc.name, e)
                            tool_results.append(genai_types.Part(
                                function_response=genai_types.FunctionResponse(
                                    name=fc.name,
                                    response={"error": str(e)},
                                )
                            ))

                    messages.append(genai_types.Content(role="user", parts=tool_results))

                logger.warning("Agent hit max turns (%d)", settings.scrape_max_agent_turns)
                return None
