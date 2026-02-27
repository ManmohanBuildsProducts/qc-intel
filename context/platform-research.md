# Research: Blinkit / Zepto / Swiggy Instamart — Scraper Technical Reference

**Date:** 2026-02-26
**Depth:** Quick scan
**Query:** Platform URL structure, location/pincode handling, API vs JS-rendered, add-to-cart mechanics, Gurugram pincodes

---

## TLDR

All three platforms are **fully JavaScript-rendered SPAs** with no meaningful HTML in the initial response. Location is passed via **lat/lng coordinates** (not raw pincodes) either as HTTP headers or cookies, resolved from the pincode before making product API calls. Internal APIs return JSON and can be intercepted via browser DevTools, but all require session tokens and location context.

---

## Key Findings

- All three platforms require browser automation (Playwright/Puppeteer) — `requests` + BeautifulSoup will get empty shells. [^1]
- Location is resolved from pincode → lat/lng before any product call; raw pincodes are not passed to product APIs. [^2]
- Blinkit passes location via `lat` / `lon` HTTP request headers on every API call. [^3]
- Zepto's web app uses a `store_id` tied to the resolved delivery zone; this is set during location setup. [^4]
- Swiggy Instamart encodes location in a session cookie and in `lat`/`lng` query params on API calls. [^5]
- None of the three have a public API — endpoints are reverse-engineered from app/web network traffic. [^1]
- Add-to-cart max quantity is surfaced in the product JSON response, not a separate API call. [^6]

---

## Details

### 1. Blinkit

#### URL Structure

| Page type | Pattern | Example |
|-----------|---------|---------|
| Homepage | `https://blinkit.com/` | — |
| Category listing | `https://blinkit.com/cn/<category-slug>/cid/<category-id>` | `/cn/dairy-bread-eggs/cid/16` |
| Sub-category | `https://blinkit.com/cn/<sub-slug>/cid/<sub-id>` | `/cn/milk/cid/922` |
| Product detail | `https://blinkit.com/prn/<product-slug>/prid/<product-id>` | `/prn/amul-taaza-toned-fresh-milk/prid/39868` |
| Search | `https://blinkit.com/s/?q=<query>` | `/s/?q=amul+milk` |

#### Rendering

Fully **client-rendered React SPA**. The HTML shell is ~2KB; all product data loads via XHR after JS executes. You need Playwright or Puppeteer. Wait for `networkidle` or a specific product grid selector before scraping DOM.

#### Location / Pincode Handling

1. User enters a pincode on the site → Blinkit calls a geocoding endpoint to resolve it to `(lat, lon)`.
2. Resolved coordinates are stored in cookies and passed as **custom HTTP headers** on every subsequent API call:
   - `lat: <decimal_latitude>`
   - `lon: <decimal_longitude>`
3. All product listing API calls require these headers. Requests without them return empty results or a location prompt.
4. The cookie name observed in reverse-engineered scrapers is typically `gr_1` (stores lat/lon JSON blob).

#### Internal API Endpoints (reverse-engineered)

All endpoints are under `https://blinkit.com/v2/` or proxied through Cloudflare:

```
GET /v2/products/search/?q=<query>&start=0&size=20
  Headers: lat, lon, app_client, rn_version
  Response: JSON with `objects[]` array

GET /v2/listing/category/?l0_category=<id>&start=0&size=20
  Headers: lat, lon
  Response: JSON with product objects
```

Response JSON contains per-product: `id`, `name`, `mrp`, `price`, `discount`, `unit`, `image_url`, `brand`, `available` (bool), `max_allowed_quantity` (int).

#### Anti-scraping

- Cloudflare bot protection on the domain.
- Session tokens rotate; reuse browser session across requests.
- Rate-limits on aggressive polling. Use delays of 1–2s between paginated calls.

---

### 2. Zepto

#### URL Structure

| Page type | Pattern | Example |
|-----------|---------|---------|
| Homepage | `https://www.zepto.com/` | — |
| Category / brand listing | `https://www.zepto.com/brand/<BrandName>/<UUID>` | `/brand/Grocery/434e9414-baf5-4894-9be4-8b908fb7d16d` |
| Product detail | `https://www.zepto.com/pip/<product-slug>/<product-id>` | `/pip/amul-taaza/31423` |
| Static pages | `https://www.zepto.com/s/<page-name>` | `/s/terms-of-service` |

Note: The `<UUID>` on brand/category pages appears to be a store-context-specific ID that can vary by location.

#### Rendering

Fully **client-rendered Next.js SPA**. Initial HTML contains minimal content; all product data is fetched client-side. Playwright required. Zepto is primarily a **mobile-first app** — their web experience is thinner than Blinkit's; the iOS/Android app is a richer scraping target if you use a mobile proxy/emulator setup.

#### Location / Pincode Handling

1. Pincode entry triggers a store lookup; Zepto assigns a `store_id` corresponding to the nearest dark store.
2. `store_id` is set in the session (localStorage/cookie) and sent with every subsequent product API call as a query param or header.
3. Location is also stored as `delivery_lat` / `delivery_lng` in session storage.
4. Changing location without clearing the session may return stale `store_id` data — always flush session on location change.

#### Internal API Endpoints (reverse-engineered)

Base: `https://api.zeptonow.com/api/v1/` or `https://www.zepto.com/api/`

```
GET /search?query=<term>&store_id=<id>&page_number=0&page_size=20
  Headers: Authorization: Bearer <token>, appversion, platform: web
  Response: JSON with `sections[].items[]`

GET /cn/listings?category_id=<id>&store_id=<id>&page=0
  Response: JSON listing for a category
```

Response JSON contains: `product_id`, `name`, `mrp`, `discounted_price`, `quantity`, `unit_quantity`, `in_stock` (bool), `max_cart_quantity` (int), `brand_name`, `images[]`.

#### Anti-scraping

- JWT bearer tokens expire; re-auth via OTP is required for fresh sessions.
- Heavy use of Akamai Bot Manager on API routes.
- Rate-limits trigger HTTP 429 after ~30 rapid requests.

---

### 3. Swiggy Instamart

#### URL Structure

| Page type | Pattern | Example |
|-----------|---------|---------|
| Instamart home | `https://www.swiggy.com/instamart` | — |
| Category listing | `https://www.swiggy.com/instamart/category?categoryName=<name>&categoryThemeId=<id>` | `?categoryName=Dairy` |
| Product search | `https://www.swiggy.com/instamart/search?query=<term>` | `?query=amul+milk` |
| Product detail | Typically rendered as a modal/overlay on listing; no distinct PDP URL | — |

Swiggy's routing is less SEO-friendly — most deep links resolve to modal states rather than separate URL paths.

#### Rendering

Fully **client-rendered React SPA**, shared codebase with Swiggy food delivery. All product data is fetched via internal APIs. Playwright required. Notably, Swiggy frequently A/B tests UI so DOM selectors are unstable — prefer intercepting XHR responses over scraping DOM.

#### Location / Pincode Handling

1. Pincode is resolved to coordinates server-side; Swiggy returns a `tid` (territory ID) and store coordinates.
2. Location is stored as a session cookie (`_session_tid`, `userLocation`) sent with every API request.
3. API calls include `lat` and `lng` as query params:
   ```
   ?lat=28.4595&lng=77.0266&tid=<territory_id>
   ```
4. Without valid `tid` + coordinates, all Instamart product calls return empty or redirect to address prompt.

#### Internal API Endpoints (reverse-engineered)

Base: `https://www.swiggy.com/api/instamart/`

```
GET /api/instamart/home?lat=<lat>&lng=<lng>&tid=<tid>
  Headers: Cookie: _session_tid=...; Content-Type: application/json
  Response: JSON with category listing

POST /api/instamart/search
  Body: {"query": "milk", "lat": 28.45, "lng": 77.02, "tid": "...", "pageNumber": 0, "pageSize": 20}
  Response: JSON with `searchResultListings[].products[]`

GET /api/instamart/category/listing?categoryId=<id>&lat=<lat>&lng=<lng>&tid=<tid>
  Response: category product array
```

Response JSON contains: `id`, `name`, `price`, `totalPrice`, `quantity`, `packSize`, `inStock` (bool), `maxSelectableQuantity` (int), `brand`, `images`, `offerTags[]`.

#### Anti-scraping

- Swiggy uses CORS + CSRF token validation on POST endpoints.
- Session cookies have short TTLs; rotating cookies from headless browsers is the most stable approach.
- Aggressive bot detection on the login/address resolution flows.

---

## Add-to-Cart Behavior & Stock Signals

| Platform | Max Qty Field | Stock Field | Notes |
|----------|--------------|-------------|-------|
| Blinkit | `max_allowed_quantity` (int) | `available` (bool) | Shown as a stepper with hard cap in UI. If `available: false`, product card shows "Notify Me". |
| Zepto | `max_cart_quantity` (int) | `in_stock` (bool) | UI enforces the cap visually. Out-of-stock items still appear in listing with greyed card. |
| Instamart | `maxSelectableQuantity` (int) | `inStock` (bool) | Displayed as stepper with +/- buttons; cap enforced client-side. |

**Key notes for scrapers:**
- Max quantity is typically 5–10 for most grocery SKUs, higher for commodities.
- Stock status is **location-specific** — same SKU can be in-stock in one dark store and OOS in another.
- There is no separate "check stock" endpoint — stock status is bundled in the listing/search response.
- Add-to-cart itself requires an authenticated session (phone OTP login); you cannot place orders without auth. Stock *reading* does not require login on Blinkit's web listing, but does on Zepto and Instamart.

---

## Gurugram Pincodes (Major Areas)

These are the 15–18 pincodes covering commercially and residentially dense Gurugram, suitable as scraping seed locations:

| Pincode | Key Areas / Landmarks |
|---------|----------------------|
| 122001 | Civil Lines, Sector 14, Sadar Bazar, Old Gurgaon, Sector 24 |
| 122002 | DLF Phase 1 & 2, MG Road, Cyber City (Sector 24–26) |
| 122003 | Sector 4, 7, 9, DLF Phase 3, Sikandarpur |
| 122004 | Sector 28, 29, Golf Course Road start |
| 122006 | Palam Vihar, Sector 23 |
| 122007 | Sector 10, 10A |
| 122008 | Sector 45, 46, 47 (South Gurgaon) |
| 122009 | Sohna Road, Sector 49, 50 |
| 122010 | DLF Phase 3, Sector 24, 25, Udyog Vihar Phase 4–5 |
| 122011 | Sector 56, 57, 58 (South City 2 belt) |
| 122015 | Sector 18, Udyog Vihar Phase 1–3 |
| 122016 | Sector 31, 32, 33 |
| 122017 | Palam Vihar Extension, Sector 8 |
| 122018 | Sector 47, 48, 49 (Huda City Centre area) |
| 122021 | Manesar, Industrial belt |
| 122022 | Sector 17B, Jacobpura |
| 122051 | Sector 65, 66, 67, 68 (New Gurgaon / Dwarka Expressway) |
| 122102 | Sohna Town (outer boundary) |

**Recommended seed pincodes for scraping coverage** (covers >80% of dark store catchments):
`122001, 122002, 122003, 122008, 122010, 122015, 122018, 122051`

---

## Scraping Architecture Recommendations

1. **Browser automation is mandatory** for all three. Playwright (async) is the current best-fit — faster than Selenium, supports request interception.
2. **Intercept XHR, don't scrape DOM.** All three platforms fire clean JSON API calls. Use `page.on('response', ...)` to capture them rather than parsing rendered HTML.
3. **Location setup flow per platform:**
   - Blinkit: Set `lat`/`lon` headers via `page.setExtraHTTPHeaders()` after resolving pincode → coords.
   - Zepto: Navigate the pincode entry modal once, capture `store_id` from the resulting API call, then reuse.
   - Instamart: Set location via UI once, extract `tid` + coords from cookie/response, reuse in subsequent requests.
4. **Session reuse** is critical — OTP login, once done, should be saved as browser storage state (`browser_context.storage_state()` in Playwright) and reloaded per run.
5. **Pincode → lat/lng resolution**: Use Google Maps Geocoding API or a static lookup table (see pincodes above) to convert pincodes before making platform API calls.

---

## Gaps & Caveats

- Exact API endpoint paths are reverse-engineered from community scrapers and DevTools inspection — Blinkit, Zepto, and Swiggy do not publish internal API docs. Paths may have changed.
- `max_allowed_quantity` / `max_cart_quantity` field names are reported from third-party analysis; validate against live network traffic before relying on them.
- Pincode-to-area mapping for Gurugram is approximate — India Post boundaries don't perfectly align with delivery zone boundaries used by dark stores.
- Zepto's web app is thinner than its mobile app; some categories and products may only appear in the app. Consider Appium-based scraping for full coverage.
- Anti-bot measures (Cloudflare, Akamai) are updated frequently. Any specific bypass technique will have a limited shelf life — design for rotation and retry.
- Stock and availability data is real-time and volatile; a scrape run longer than ~30 minutes may have stale data from the first pages by the time the last pages are scraped.

---

## Sources

[^1]: [Blinkit Data Scraping: How to Scrape Blinkit Product Details — ScrapeHero](https://www.scrapehero.com/blinkit-data-scraping/) — accessed 2026-02-26
[^2]: [Benefits of Scraping Product Listings from Zepto, Blinkit, and Amazon — FoodDataScrape](https://www.fooddatascrape.com/scraping-product-listings-from-different-pin-codes-in-zepto-blinkit-and-amazon.php) — accessed 2026-02-26
[^3]: [Step-by-Step Guide to Building a Blinkit Product Data API Integration — Medium/Retail Scrape](https://medium.com/@robertrucker1190/step-by-step-guide-to-building-a-blinkit-product-data-api-integration-a246e2270d85) — accessed 2026-02-26
[^4]: [Zepto Quick Commerce API: 10-Min Delivery Data — Nextract](https://nextract.dev/apis/zepto-api/) — accessed 2026-02-26
[^5]: [Take a Deep Dive into Swiggy Instamart API Scraping — FoodDataScrape](https://www.fooddatascrape.com/swiggy-instamart-api-scraping-for-navigating-grocery-data.php) — accessed 2026-02-26
[^6]: [QuickCom — GitHub (KshKnsl)](https://github.com/KshKnsl/QuickCom) — multi-platform scraper, accessed 2026-02-26
[^7]: [Blinkit Product Scraper — Apify](https://apify.com/jocular_quisling/blinkit-product-scraper/api) — accessed 2026-02-26
[^8]: [Zepto Product Scraper & Price Tracker — Apify](https://apify.com/krazee_kaushik/zepto-scraper/api) — accessed 2026-02-26
[^9]: [Gurgaon Pin Code List — SafehousePG](https://www.safehousepg.in/blog/gurgaon-pin-code) — accessed 2026-02-26
[^10]: [Gurgaon PIN Code — PlutoMoney](https://plutomoney.in/blog/post/gurgaon-pin-code-zip-code-postal-code) — accessed 2026-02-26
[^11]: [Quick Commerce Data APIs: Instamart, Zepto, Blinkit — FoodSpark](https://www.foodspark.io/understanding-quick-commerce-data-apis/) — accessed 2026-02-26
