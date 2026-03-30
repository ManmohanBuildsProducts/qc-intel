#!/usr/bin/env python3
"""Test Zepto add-to-cart to check if it reveals real stock beyond the 50 cap.

Interactive: requires user to provide OTP for Zepto login.
Writes OTP prompt to /tmp/zepto_otp_needed.txt and reads from /tmp/zepto_otp.txt.
"""

import asyncio
import json
import logging
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

PHONE = "7060334569"
LAT, LNG = 26.8607, 75.7633
PINCODE = "302020"
OTP_FILE = "/tmp/zepto_otp.txt"
OTP_PROMPT = "/tmp/zepto_otp_needed.txt"


def _stealth_path():
    return os.path.join(os.path.dirname(__file__), "..", "src", "agents", "scraper", "stealth.js")


def rt(result):
    return "".join(c.text for c in result.content if hasattr(c, "text"))


def pv(result):
    text = rt(result)
    m = re.search(r"### Result\s*\n(.*?)(?:\n###|\Z)", text, re.DOTALL)
    if m:
        raw = m.group(1).strip()
        if raw.startswith('"') and raw.endswith('"'):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return raw
        return raw
    return text


def wait_for_otp():
    """Wait for OTP file to appear."""
    # Signal that OTP is needed
    with open(OTP_PROMPT, "w") as f:
        f.write("ENTER OTP IN /tmp/zepto_otp.txt\n")

    print(f"\n{'='*60}")
    print(f"  OTP sent to {PHONE}")
    print(f"  Write the OTP to: {OTP_FILE}")
    print(f"  Example: echo '123456' > {OTP_FILE}")
    print(f"{'='*60}\n")

    # Remove old OTP file if exists
    if os.path.exists(OTP_FILE):
        os.remove(OTP_FILE)

    # Wait for new OTP file
    for _ in range(120):  # 2 min timeout
        if os.path.exists(OTP_FILE):
            with open(OTP_FILE) as f:
                otp = f.read().strip()
            if otp and len(otp) >= 4:
                os.remove(OTP_FILE)
                os.remove(OTP_PROMPT)
                return otp
        time.sleep(1)

    return None


async def main():
    stealth = _stealth_path()
    args = [
        "@playwright/mcp@latest", "--browser", "firefox",
        "--headless", "--caps", "code-execution",
    ]
    if os.path.exists(stealth):
        args += ["--init-script", stealth]

    server = StdioServerParameters(command="npx", args=args)
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            try:
                # Step 1: Navigate to Zepto
                logger.info("Step 1: Navigate to Zepto...")
                await session.call_tool("browser_navigate", {"url": "https://www.zepto.com"})
                await session.call_tool("browser_wait_for", {"time": 5000})

                # Step 2: Click login
                logger.info("Step 2: Click login button...")
                await session.call_tool("browser_click", {"element": "login button", "ref": "e27"})
                await session.call_tool("browser_wait_for", {"time": 2000})

                # Step 3: Check what appeared
                snap = await session.call_tool("browser_snapshot", {})
                snap_text = rt(snap)

                # Look for phone input
                if "phone" in snap_text.lower() or "mobile" in snap_text.lower() or "number" in snap_text.lower():
                    logger.info("Step 3: Login modal appeared, entering phone number...")

                    # Type phone number
                    await session.call_tool("browser_type", {
                        "element": "phone number input",
                        "ref": "",
                        "text": PHONE,
                    })
                    await session.call_tool("browser_wait_for", {"time": 1000})

                    # Take screenshot to verify
                    ss = await session.call_tool("browser_take_screenshot", {})
                    ss_text = rt(ss)
                    # Extract screenshot path
                    ss_match = re.search(r'\((.*?\.png)\)', ss_text)
                    if ss_match:
                        print(f"Screenshot: {ss_match.group(1)}")

                    # Click send OTP / continue button
                    snap2 = await session.call_tool("browser_snapshot", {})
                    snap2_text = rt(snap2)

                    # Find and save snapshot for debugging
                    with open("/tmp/zepto_login_snap.txt", "w") as f:
                        f.write(snap2_text)

                    # Print relevant elements
                    for line in snap2_text.split("\n"):
                        ll = line.lower()
                        if any(w in ll for w in ["otp", "send", "continue", "verify", "submit", "phone", "number", "input", "textbox"]):
                            print(f"  {line.strip()[:120]}")

                else:
                    logger.warning("Login modal not found. Snapshot:")
                    print(snap_text[:500])

            finally:
                # Don't close browser yet — we need it for the rest of the flow
                pass


if __name__ == "__main__":
    asyncio.run(main())
