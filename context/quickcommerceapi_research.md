# QuickCommerce API — Research Report

**Date:** 2026-03-29
**Target:** https://quickcommerceapi.com (API at `api.quickcommerceapi.com`)
**Purpose:** Methodology analysis + security surface assessment

---

## 1. What They Are

A commercial API-as-a-service that wraps **7 Indian quick commerce platforms** into a single REST API:
- BlinkIt, Zepto, Swiggy Instamart, BigBasket, DMart Ready, JioMart, Flipkart Minutes

**Business model:** Prepaid credits. 1 API call = 1 credit.
| Pack | Credits | Price | Per Credit |
|------|---------|-------|------------|
| Trial | 250 (promo) | Free | Free |
| Starter | 2,500 | ₹500 | ₹0.20 |
| Pro | 50,000 | ₹7,500 | ₹0.15 |
| Scale | 2,00,000 | ₹20,000 | ₹0.10 |

**Stack:** FastAPI backend, Next.js frontend, Razorpay payments, JWT auth, SQLite or Postgres (unknown).

---

## 2. How They Scrape Inventory Data (Methodology)

Based on cross-referencing their API responses, the Jatin Banga dark stores article (same API patterns), and our own QC Intel codebase, here's how they almost certainly do it:

### 2.1 Platform-Specific Internal APIs

| Platform | Endpoint | Method | Auth |
|----------|----------|--------|------|
| **Blinkit** | `POST api2.grofers.com/v1/layout/feed` or `/v1/layout/search` | POST with lat/lon/auth_key headers | Cookie/session-based, Cloudflare TLS fingerprint check |
| **Zepto** | `GET api.zepto.com/api/v3/search` or `/api/v4/catalog` | GET with localStorage-based location | Unauthenticated for search; Bearer token for deep data |
| **Swiggy Instamart** | `GET www.swiggy.com/api/instamart/search` | GET with lat/lng cookies | AWS WAF + SPA session cookies |
| **BigBasket** | Likely `/pd/search/` or similar internal API | Unknown | Unknown |
| **DMart/JioMart/Minutes** | Requires pincode header (`x-geolocation-pincode`) | Unknown | Unknown |

### 2.2 Core Technique: XHR/Fetch Interception

They are **not scraping DOM** — they're intercepting the internal API calls that the platform frontends make. The approach:

1. **Launch headless browser** (Playwright/Puppeteer) with stealth patches
2. **Patch `window.fetch`** before page loads to capture API responses matching known URL patterns
3. **Navigate to platform** with spoofed location (lat/lon via headers, cookies, or localStorage)
4. **Capture JSON responses** from the platform's own internal APIs
5. **Parse standardized fields** (product ID, name, brand, price, MRP, inventory count, availability, rating, images)

### 2.3 Key Data Fields They Extract

From the API response structure, they return:
- `inventory` — **real stock count** (not just boolean in_stock)
- `offer_price` / `mrp` — current selling price vs MRP
- `available` — boolean stock status
- `platform.sla` — delivery ETA ("8 mins")
- `platform.open` — store operational status
- `store_id` — specific dark store serving that location
- `deeplink` — direct purchase URL
- `rating` / `rating_count` — user ratings

### 2.4 Anti-Detection

Based on common patterns in this space:
- **TLS fingerprint spoofing** (curl_cffi with Chrome impersonation for Blinkit's Cloudflare)
- **Stealth browser patches** (navigator.webdriver, chrome runtime, WebGL masking)
- **Datacenter proxy pools** (Bright Data or similar — Blinkit and Instamart don't filter datacenter IPs)
- **Location spoofing** via GPS coordinates in headers/cookies/localStorage
- **Rate limiting awareness** (100 req/min on their own API; unknown rate on upstream platforms)

### 2.5 Real-Time vs Cached

Their `<2s avg response time` claim and `fetched_at` timestamps in responses suggest they scrape **on-demand per API call** rather than caching. Each customer request triggers a fresh scrape of the target platform. This is expensive but provides truly real-time data.

---

## 3. Security Findings

### 3.1 CRITICAL: Full OpenAPI Spec Exposed

**URL:** `https://api.quickcommerceapi.com/openapi.json`
- **99KB** complete OpenAPI 3.1.0 specification
- Exposes **ALL endpoints** including admin, auth, payments, dashboard
- Includes full request/response schemas
- **No authentication required** to access

### 3.2 CRITICAL: Swagger UI & ReDoc Publicly Accessible

- **Swagger UI:** `https://api.quickcommerceapi.com/docs` (interactive API explorer)
- **ReDoc:** `https://api.quickcommerceapi.com/redoc` (formatted documentation)
- Both render the full OpenAPI spec including internal endpoints

### 3.3 HIGH: Admin Endpoints Documented in OpenAPI

The OpenAPI spec reveals admin-only endpoints:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/admin/users` | GET | List all users (search by query) |
| `/api/admin/coupons` | GET/POST | List/create coupons |
| `/api/admin/coupons/{id}` | PATCH | Modify coupons |
| `/api/admin/grant-credits` | POST | Grant free credits to any user |
| `/api/admin/user-credits` | GET | Check any user's credit balance |

**Current protection:** These require an `authorization` header (JWT Bearer token). They return 422 (missing field) without it — NOT 401/403. This means:
- The auth check happens at the Pydantic validation level, not middleware
- If an admin JWT is compromised, full access to user management and credit granting
- The schema for `GrantCreditsRequest` is fully documented: `{user_email, credits, reason, expiry_days}`

### 3.4 HIGH: No Security Schemes Defined

The OpenAPI spec has:
```json
"securitySchemes": {}  // EMPTY
"security": []         // EMPTY (global)
```
Every endpoint has `"Security: NONE SPECIFIED"` in the spec. This means:
- Swagger UI won't prompt for authentication when testing endpoints
- Automated scanners will flag every endpoint as unauthenticated
- While the server does enforce auth at runtime, the spec doesn't declare it

### 3.5 MEDIUM: Payment Webhook Endpoint Exposed

`POST /api/payments/webhook` — Razorpay webhook handler
- Schema fully documented in OpenAPI
- If webhook signature verification is weak or missing, could be exploited for:
  - Credit injection (fake payment.captured events)
  - Order status manipulation

### 3.6 MEDIUM: Full Auth Flow Documented

The OpenAPI reveals the complete authentication flow:
1. `POST /api/auth/signup` — email, name, password
2. `POST /api/auth/verify-email` — 4-digit verification code
3. `POST /api/auth/login` — returns JWT access + refresh tokens
4. `POST /api/auth/refresh` — refresh token rotation
5. `POST /api/auth/forgot-password` / `reset-password`

**Risk:** The 4-digit verification code is a small keyspace (0000-9999). If not rate-limited, brute-forceable.

### 3.7 LOW: LLM Context Files Exposed

- `https://quickcommerceapi.com/llms.txt` — summary for LLM crawlers
- `https://quickcommerceapi.com/llms-full.txt` — **complete API reference** including all endpoints, schemas, MCP config

These are intentionally public (for AI discoverability), but they document internal implementation details.

### 3.8 LOW: Dashboard Endpoints Documented

All dashboard endpoints are documented:
- `/api/dashboard/me` — user profile
- `/api/dashboard/credits` — credit balance
- `/api/dashboard/usage` — API usage history
- `/api/dashboard/reset-key` — API key reset (2-step with email confirmation)
- `/api/dashboard/social-shares` — social sharing rewards system

### 3.9 INFO: Undocumented Endpoint

`GET /v1/compare` exists in the OpenAPI spec but is NOT in their public documentation. Requires API key (returns 401 without one).

---

## 4. Comparison: Their Approach vs Our QC Intel Approach

| Aspect | QuickCommerce API | QC Intel |
|--------|------------------|----------|
| **Platforms** | 7 (+ DMart, JioMart, BigBasket, Minutes) | 3 (Blinkit, Zepto, Instamart) |
| **Data freshness** | Real-time (on-demand scraping) | Twice daily (morning/night snapshots) |
| **Inventory method** | Direct count from platform API | Same — direct from API response |
| **Sales estimation** | Not offered | morning - night inventory delta |
| **Normalization** | Not offered (raw platform data) | Cross-platform product matching via embeddings |
| **Analytics** | Not offered | Gemini-powered market reports |
| **Scraping tech** | Likely headless browser + XHR intercept | Playwright MCP + XHR intercept (same pattern) |
| **Anti-detection** | TLS fingerprinting + proxies | Stealth.js + browser patches |
| **Business model** | API-as-a-service (credits) | Internal intelligence platform |
| **Coverage** | All India (any lat/lon) | Gurugram + Jaipur only |

**Key insight:** They solve the **data access** problem but NOT the **intelligence** problem. They give raw platform data; we add the analytics layer (sales estimation, normalization, competitive reports). These are complementary — we could potentially use their API as an alternative data source for platforms we don't currently scrape (BigBasket, DMart, JioMart, Minutes).

---

## 5. Recommendations

### For Security Report to QuickCommerce API

1. **Disable `/openapi.json`, `/docs`, `/redoc` in production** — or at minimum, require admin auth
2. **Add `securitySchemes` to OpenAPI spec** — even if auth is enforced at runtime
3. **Rate-limit email verification** — 4-digit code is brute-forceable without rate limiting
4. **Verify Razorpay webhook signatures** — reject unsigned/invalid webhook payloads
5. **Return 401/403 for admin endpoints** without auth, not 422 (leaks that the route exists and accepts requests)
6. **Remove admin endpoints from public OpenAPI spec** — or serve a public spec and a separate admin spec

### For QC Intel

1. **Consider using their API** as a data source for platforms we don't scrape (BigBasket, DMart, JioMart, Minutes) — at ₹0.10-0.20/call, 4 extra platforms per product per day = ~₹1/product/day
2. **Our moat is the analytics layer** — sales estimation, normalization, and reporting are where our value lives, not raw scraping
3. **Their methodology confirms our approach** — XHR interception of internal platform APIs is the industry standard technique
