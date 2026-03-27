# Research: Swiggy Instamart Scraping — Playwright MCP + XHR Interception

**Date:** 2026-03-27
**Depth:** Deep dive
**Query:** Best techniques for scraping Swiggy Instamart product data in 2025-2026 using Playwright MCP, with focus on XHR interception to bypass accessibility snapshot fragility.

---

## TLDR

The Swiggy Instamart search API endpoint is publicly documented in community sources and follows a predictable URL structure. The right strategy is **XHR response capture via `page.on('response')`** — not direct `fetch()` calls (which are blocked by AWS WAF) and not DOM parsing. The critical finding is that the official `@playwright/mcp` server does expose a `browser_network_requests` tool for listing requests, a `browser_run_code` tool that can run arbitrary Playwright code (including `page.on('response')`), and an optional `--caps=network` mode that adds `browser_route` / mock capabilities. An `--init-script` flag also allows patching `window.fetch` before page load.

---

## Key Findings

- **The Swiggy Instamart search API endpoint is known**: `https://www.swiggy.com/api/instamart/search?query=<term>&storeId=<id>&primaryStoreId=<id>&limit=40&pageNumber=0&...` — requires cookies and correct headers (cookies are the blocker, not the URL structure itself) [^1]
- **`page.on('response')` is the canonical Playwright pattern for XHR capture** — works in normal Playwright scripts; the browser renders the page, the API fires internally, and you capture the response body before it reaches the DOM [^3][^4]
- **Microsoft's `@playwright/mcp` exposes `browser_run_code`** — runs arbitrary Playwright code with access to the `page` object, which means `page.on('response')` and `page.waitForResponse()` are available through this tool [^6]
- **`@playwright/mcp` also has `browser_network_requests`** (always-on) and opt-in `browser_route` (via `--caps=network`) for mocking — but `browser_route` mocks requests rather than captures live responses [^6]
- **`--init-script` flag exists in `@playwright/mcp`** — loads a JS file that runs before any page scripts, enabling `window.fetch` patching or a Service Worker registration [^6]
- **The `executeautomation/mcp-playwright` alternative MCP server** has `Playwright_expect_response` + `Playwright_assert_response` tools that explicitly return `responseBody` as JSON — purpose-built for this use case [^2]
- **AWS WAF blocks direct fetch() calls from browser context** because those calls lack the session-establishing headers that a real navigation sets — cookies, device fingerprint, and timing patterns [^1][^5]
- **Service Workers intercept Playwright `page.route()` by default** — if Swiggy uses a Service Worker (likely for PWA caching), Playwright's `page.route()` won't see those requests; must set `serviceWorkers: 'block'` in browser context [^4]

---

## Details

### 1. The Swiggy Instamart API Endpoint

The actual endpoint has been documented in community discussions [^1]:

```
GET https://www.swiggy.com/api/instamart/search
  ?pageNumber=0
  &searchResultsOffset=0
  &limit=40
  &query=<search_term>
  &ageConsent=false
  &layoutId=2671
  &pageType=INSTAMART_AUTO_SUGGEST_PAGE
  &isPreSearchTag=false
  &highConfidencePageNo=0
  &lowConfidencePageNo=0
  &voiceSearchTrackingId=
  &storeId=<store_id>
  &primaryStoreId=<store_id>
  &secondaryStoreId=<secondary_store_id>
```

**Critical parameters:**
- `storeId` / `primaryStoreId` / `secondaryStoreId` — these are location-specific and change by pincode. They are embedded in the session established during navigation.
- `layoutId` — appears to be `2671` for standard search results.
- `pageType` — use `INSTAMART_AUTO_SUGGEST_PAGE` for keyword search, `INSTAMART_PRE_SEARCH_PAGE` for pre-search.

**Why direct fetch fails**: Calling this URL via `fetch()` inside the page or via Python `requests` returns an AWS WAF block. The WAF checks: session cookies established during page load (`_sid`, device token, CSRF token), correct `Referer` / `Origin` headers, and likely request timing and fingerprint signals. The session cookies are only available after navigating to the Instamart page and setting a location. [^1][^5]

**Working approach (from community)**: Use Playwright to navigate to `https://swiggy.com/instamart`, set the location (by pincode), then listen to network responses — the actual search API fires as a browser-internal XHR when the user types in the search box. Capture that response rather than re-making the request. [^1]

---

### 2. Playwright `page.on('response')` Pattern

This is the canonical approach for capturing XHR/fetch responses from SPAs. [^3][^4]

**Python:**
```python
import asyncio
from playwright.async_api import async_playwright

async def scrape_instamart(query: str):
    captured = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            service_workers='block'  # Required: prevents SW from hiding requests
        )
        page = await context.new_page()

        # Register listener BEFORE navigation
        async def handle_response(response):
            if 'instamart/search' in response.url and response.status == 200:
                try:
                    data = await response.json()
                    captured.append(data)
                except Exception:
                    pass

        page.on('response', handle_response)

        # Navigate and trigger the search
        await page.goto('https://www.swiggy.com/instamart', wait_until='networkidle')
        # ... set location, type query ...
        await page.fill('input[type="search"]', query)
        await page.keyboard.press('Enter')
        await page.wait_for_timeout(3000)  # wait for XHR to fire

        await browser.close()
    return captured
```

**Alternative — `page.waitForResponse()`** (blocks until response arrives):
```python
async with page.expect_response(
    lambda r: 'instamart/search' in r.url and r.status == 200
) as response_info:
    await page.fill('input[type="search"]', query)
    await page.keyboard.press('Enter')

response = await response_info.value
data = await response.json()
```

**Key points:**
- The listener must be registered BEFORE any navigation or action that triggers the XHR.
- `page.on('response')` receives `Response` objects; call `await response.json()` or `await response.body()` to get the body.
- Bodies are only available synchronously during the handler; calling `.json()` later may fail if the response is already gone from memory. [^3][^4]

---

### 3. `@playwright/mcp` (Microsoft) Tool Inventory

The official Microsoft MCP server (`@playwright/mcp`) exposes these relevant tools: [^6]

**Always available (no extra flags):**

| Tool | What it does | Relevance |
|------|-------------|-----------|
| `browser_navigate` | Navigate to URL | Navigate to Instamart |
| `browser_evaluate` | Run JS expression on page/element | Can read `window.__STORE__`, DOM data |
| `browser_run_code` | Run a full `async (page) => {...}` Playwright code block | **Full access to `page.on('response')`** |
| `browser_network_requests` | List all network requests since page load | Shows URLs but NOT response bodies |
| `browser_snapshot` | Accessibility tree of current page | Current fallback approach |
| `browser_type` / `browser_click` | UI interactions | Trigger search, set location |
| `browser_wait_for` | Wait for text/time | Wait for results to load |

**Opt-in via `--caps=network`:**

| Tool | What it does |
|------|-------------|
| `browser_route` | Mock a URL pattern with static response body |
| `browser_route_list` | List active routes |
| `browser_unroute` | Remove a route |
| `browser_network_state_set` | Set browser online/offline |

**Important limitation**: `browser_network_requests` lists request URLs and methods but **does not return response bodies**. It is useful for discovering which XHR endpoints fire, but you cannot get the product JSON from it directly.

**`browser_run_code` is the unlock**: This tool accepts `async (page) => { ... }` and runs it with a real Playwright `page` object. This means you can do:

```javascript
async (page) => {
  const results = [];
  page.on('response', async (response) => {
    if (response.url().includes('instamart/search') && response.status() === 200) {
      const data = await response.json();
      results.push(data);
    }
  });
  // then trigger the search action
  await page.waitForTimeout(3000);
  return results;
}
```

**Limitation of `browser_run_code` with event listeners**: The `page.on('response', ...)` callback fires asynchronously. Since `browser_run_code` returns when the function resolves, you need the search action AND the listener inside the same `browser_run_code` invocation to ensure both run before the function returns. A `page.waitForResponse()` (promise-based) inside the function is cleaner and more reliable.

---

### 4. `--init-script` for Fetch Patching

The `@playwright/mcp` server supports `--init-script <path>` which loads a JavaScript file that runs **before any page scripts**. This is the `addInitScript` equivalent. [^6]

This enables the fetch proxy pattern:

```javascript
// init-script.js — runs before page scripts load
const originalFetch = window.fetch;
window.__interceptedResponses = [];

window.fetch = async function(...args) {
  const response = await originalFetch.apply(this, args);
  const url = typeof args[0] === 'string' ? args[0] : args[0].url;
  if (url && url.includes('instamart/search')) {
    const clone = response.clone();
    clone.json().then(data => {
      window.__interceptedResponses.push({ url, data });
    }).catch(() => {});
  }
  return response;
};
```

After page actions, retrieve with `browser_evaluate`:
```javascript
() => window.__interceptedResponses
```

**Tradeoff**: This only intercepts `fetch()` calls, not XHR (`XMLHttpRequest`). Swiggy may use either. Also, if Swiggy's Service Worker intercepts requests before they reach the page's fetch, this won't work. The `page.on('response')` approach via `browser_run_code` is more reliable since Playwright captures at the network level.

---

### 5. `executeautomation/mcp-playwright` Alternative

This is a community MCP server that is different from Microsoft's `@playwright/mcp`. It has explicit tools for response capture: [^2]

```
Playwright_expect_response(id, url)  →  starts waiting for a response matching url
Playwright_assert_response(id)       →  returns { statusCode, responseUrl, responseBody (JSON string) }
```

**Usage pattern for Instamart:**
1. Call `Playwright_expect_response(id="search_resp", url="**/instamart/search**")`
2. Call `Playwright_fill` + `Playwright_press` to trigger the search
3. Call `Playwright_assert_response(id="search_resp")` — returns the full JSON body

This is arguably the cleanest approach if using this MCP server variant, as it's specifically designed for this pattern without needing `browser_run_code`.

---

### 6. React SPA Data Extraction Alternatives

When `page.on('response')` is not accessible (or as a complement): [^5]

#### Option A: `__NEXT_DATA__` / `window.__STORE__`
Many React/Next.js apps embed initial state in a `<script id="__NEXT_DATA__">` tag. Swiggy likely has some initial state in the DOM.

```python
data = await page.evaluate("""
  () => {
    const el = document.querySelector('#__NEXT_DATA__');
    return el ? JSON.parse(el.textContent) : null;
  }
""")
```
**Limitation**: Only captures SSR data, not the post-search XHR results.

#### Option B: Walking React Fiber Tree
```javascript
() => {
  const root = document.querySelector('[data-testid="default_container"]');
  const fiber = root?._reactFiber || root?.__reactFiber ||
    Object.keys(root).find(k => k.startsWith('__reactFiber'));
  // ... traverse memoizedProps
}
```
**Limitation**: Fragile, breaks with React version updates and minification. Not recommended for production.

#### Option C: CDP Session (Direct Playwright API, not MCP)
If running Playwright directly (not via MCP), you can get a CDP session:
```python
client = await context.new_cdp_session(page)
await client.send('Network.enable')
client.on('Network.responseReceived', lambda event: ...)
client.on('Network.loadingFinished', lambda event: ...)
```
**Limitation**: Microsoft's `@playwright/mcp` does not expose raw CDP session access through its tools, though it does support `--cdp-endpoint` for connecting to an external browser via CDP.

#### Option D: `performance.getEntries()`
Only returns timing and URL metadata, not response bodies. Not useful for extracting product data.

#### Option E: Service Worker Proxy (init-script)
Register a Service Worker via `--init-script` to intercept all fetch responses:
```javascript
// init-script.js
navigator.serviceWorker.register('/sw-interceptor.js')
```
This requires the target site to allow SW registration from your origin (it won't, since it's a cross-origin SW). Not viable for third-party site scraping.

---

### 7. Handling AWS WAF and Location State

Swiggy Instamart has two layers of protection: [^1][^5]

1. **AWS WAF**: Blocks requests that don't have session cookies from a real navigation. Solution: always navigate to the page and set location before triggering search. Don't try to replay cookies manually — they expire and rotate.

2. **Location state (storeId)**: The `storeId` and `primaryStoreId` are not fixed per pincode — they appear to be dynamically resolved during location-setting. Capture them by listening to the location-setting API calls (the same `page.on('response')` pattern, but filtering for the location API endpoint).

**Recommended session flow:**
```
1. navigate('https://www.swiggy.com/instamart')
2. Click location selector, type pincode, confirm location
   → Capture storeId from location API response
3. Type search query in search bar, press Enter
   → Capture product data from search API response
4. Repeat step 3 for each search term (reuse session, don't re-navigate)
```

Reusing the browser session (not relaunching) is critical — AWS WAF is more likely to allow requests from a session that has demonstrated human-like navigation patterns.

---

## Data Tables

### `@playwright/mcp` Tool Comparison for XHR Capture

| Approach | Tool(s) | Gets Response Body | Notes |
|----------|---------|-------------------|-------|
| `browser_network_requests` | Always-on | No — URLs only | Useful to discover which endpoints fire |
| `browser_run_code` with `page.on('response')` | Always-on | **Yes** | Most reliable; requires callback+action in same block |
| `browser_run_code` with `page.waitForResponse()` | Always-on | **Yes** | Cleaner; promise-based |
| `browser_route` (--caps=network) | Opt-in | N/A — intercepts, doesn't capture | Useful for mocking, not data extraction |
| `browser_evaluate` reading `window.__NEXT_DATA__` | Always-on | Partial (SSR only) | Misses dynamic search results |
| `--init-script` fetch patch + `browser_evaluate` | Config flag | **Yes** (fetch only) | Works for fetch, not XHR |

### `executeautomation/mcp-playwright` vs `@playwright/mcp`

| Feature | `@playwright/mcp` (Microsoft) | `executeautomation/mcp-playwright` |
|---------|------------------------------|-----------------------------------|
| Response body capture | `browser_run_code` (indirect) | `Playwright_expect_response` + `Playwright_assert_response` (direct) |
| Network mocking | `browser_route` (--caps=network) | Not listed |
| Init script support | `--init-script` flag | Not listed |
| Accessibility snapshots | `browser_snapshot` | `Playwright_get_visible_html` |
| Stars (as of 2026-03) | 29.8k | Lower, community project |
| Maintenance | Microsoft-backed | Community |

---

## Recommended Implementation Strategy

Given the constraints (Playwright MCP, AWS WAF, SPA-internal auth), the recommended approach is:

**Primary: `browser_run_code` with `page.waitForResponse()`**

Use a single `browser_run_code` invocation that:
1. Registers the response listener
2. Triggers the search action
3. Awaits the response promise
4. Returns the JSON data

This bypasses the AWS WAF (real browser session), avoids accessibility snapshot fragility (doesn't parse DOM), and is available without any extra `--caps` flags.

**Secondary: `--init-script` fetch patch**

If `browser_run_code` callback timing proves unreliable, use `--init-script` to patch `window.fetch` globally on startup, then retrieve accumulated data with `browser_evaluate` after each search action.

**Avoid**: Direct `fetch()` calls from inside `page.evaluate()` — these are blocked by AWS WAF because they don't carry session cookies established by the navigation.

---

## Gaps & Caveats

- The `storeId` / `primaryStoreId` values for Gurugram pincodes were not verified in this research — they need to be captured dynamically from the location-setting API response, not hardcoded.
- The Reddit thread showing the API endpoint is ~1 year old; Swiggy may have changed `layoutId` or `pageType` values. These should be verified by observing live network traffic.
- It's unclear whether Swiggy uses XHR (`XMLHttpRequest`) or `fetch()` for the search API internally. If it uses XHR, the `--init-script` fetch-patch approach won't capture it; `page.on('response')` captures both.
- The `browser_run_code` tool in `@playwright/mcp` has not been personally verified for whether `page.on('response')` callbacks fire correctly within its execution sandbox — this needs a quick test.
- Swiggy's Service Worker status (whether it intercepts network requests) was not directly verified. Setting `serviceWorkers: 'block'` in the browser context is a safe default.
- All commercial scraping services (Bright Data, Apify, ScrapingBee) offer Instamart extractors but add cost and dependency; these are not suitable for a self-hosted intelligence pipeline.

---

## Sources

[^1]: [Help with scraping Instamart : r/webscraping](https://www.reddit.com/r/webscraping/comments/1kbdp1i/help_with_scraping_instamart/) — accessed 2026-03-27

[^2]: [Supported Tools | executeautomation/mcp-playwright](https://executeautomation.github.io/mcp-playwright/docs/playwright-web/Supported-Tools) — accessed 2026-03-27

[^3]: [How to capture background requests and responses in Playwright? — Scrapfly](https://scrapfly.io/blog/answers/how-to-capture-xhr-requests-playwright) — accessed 2026-03-27

[^4]: [Network - Playwright Official Docs](https://playwright.dev/docs/network) — accessed 2026-03-27

[^5]: [Scraping React, Vue and Angular SPAs: An In-Depth Technical Guide — Browserless](https://www.browserless.io/blog/web-scraping-api-react-vue-angular-spas) — accessed 2026-03-27

[^6]: [microsoft/playwright-mcp — GitHub (README + tool listing)](https://github.com/microsoft/playwright-mcp) — accessed 2026-03-27

[^7]: [Instamart Data Extraction: How to Scrape Instamart Product Details — ScrapeHero](https://www.scrapehero.com/scrape-instamart/) — accessed 2026-03-27

[^8]: [How to Handle Playwright Network Interception — OneUptime Blog](https://oneuptime.com/blog/post/2026-02-02-playwright-network-interception/view) — accessed 2026-03-27
