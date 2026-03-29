# Inventory Data Approach — Per Platform

**Date**: 2026-03-29
**Validated on**: Gurugram 122018 (Huda City Centre), Jaipur 302020 (Mansarovar)

## Summary

| Platform | Inventory Signal | Coverage | Cap | Cap Bypass |
|----------|-----------------|----------|-----|------------|
| **Blinkit** | `cart_item.inventory` (numeric 0-50) | 100% | 50 | Not yet tested |
| **Zepto** | `availableQuantity` from BFF gateway (numeric 0-50) | 100% | 50 | ATC probing (53-72 real) |
| **Instamart** | `inventory.inStock` (boolean only) | 100% | N/A | No numeric inventory exists |

## Zepto — BFF Gateway Interception

**Problem**: Zepto's search API at `bff-gateway.zepto.com/user-search-service/api/v3/search` is called server-side by Next.js SSR. Standard `window.fetch` patching cannot intercept it — the fetch happens in the Node.js server, not the browser's JavaScript runtime.

**Solution**: `page.waitForResponse()` via Playwright's `browser_run_code` tool. This intercepts at the browser's network level, below JavaScript. Requires `--caps=code-execution` flag on the Playwright MCP server.

```
Flow:
1. browser_run_code sets up page.waitForResponse() for 'bff-gateway'
2. page.goto() triggers the search
3. waitForResponse resolves with the full 208KB JSON response
4. Walk JSON for objects with availableQuantity + mrp + product
5. Normalize to standard schema (prices in paise ÷ 100)
```

**Key fields from BFF response**:
- `availableQuantity` — stock count (capped at 50)
- `allocatedQuantity` — items in active carts (usually 0)
- `outOfStock` — boolean
- `productVariant.maxAllowedQuantity` — per-order cart limit
- `product.name`, `product.brand` — nested under `product`
- `mrp`, `discountedSellingPrice` — in paise (not rupees)
- `productVariant.formattedPacksize` — e.g., "1 pack (500 ml)"
- `productVariant.images[]` — objects with `path`, not URL strings

## Zepto — ATC Probing (Cap Bypass)

**Problem**: Both Blinkit and Zepto cap `inventory_available` at 50 in search API. High-velocity SKUs with real stock of 100+ show as 50, making morning-night delta underestimate sales.

**Solution**: Add-to-cart probing. Guest cart works (no login required). Click ADD, then click "Increase quantity" repeatedly until the quantity stops incrementing. The cart system validates against REAL warehouse stock, not the capped display value.

```
Flow:
1. Identify products at cap (quantity >= 50 from BFF capture)
2. For each: navigate to search, click ADD, click Increase repeatedly
3. Check displayed quantity every 10 clicks via snapshot
4. When qty stops incrementing for 2 checks → that's real stock
5. Click Decrease to clear cart
```

**Results** (Gurugram 122018, 2026-03-29):
- Amul Lactose Free Milk: API=50 → ATC=54
- Nandini Good Life UHT Milk: API=50 → ATC=53
- Amul Taaza Toned Milk: API=50 → ATC=53
- Heritage Toned Milk: API=50 → ATC=53
- Heritage Long Life Milk: API=50 → ATC=53

**Caveats**:
- ~3 min per capped product (clicking + is slow at 0.15s per click)
- Search may match wrong product (~25% failure rate)
- Uses MCP `browser_click` with accessibility refs (Playwright CSS selectors don't work on Zepto)

## Blinkit — Direct API Fetch

**Approach**: Browser-side `fetch('/v1/layout/search')` returns `cart_item` objects with `inventory` field (numeric 0-50). Has worked reliably since March 27.

**Cap**: 50 (identical to Zepto). ATC probing not yet tested on Blinkit.

## Instamart — Boolean Only

**Approach**: XHR interception of `/api/instamart/search/v2`. API structure is `data.cards[].card.card.gridElements.infoWithStyle.items[].variations[]`.

**Confirmed**: The `inventory` object contains ONLY `{"inStock": true/false}`. No numeric stock count exists in Swiggy Instamart's API (verified via live capture and Apify scraper output).

**Proxy signal**: `in_stock` → `out_of_stock` transition between morning/night = 1+ units sold (floor estimate).

## Sales Estimation Logic

```
Priority 1: inventory_count delta (Blinkit/Zepto) → HIGH confidence
  - Exception: if morning_inv >= 50 (cap), downgrade to MEDIUM
  - Exception: if both at 50, downgrade to LOW (hidden sales)
Priority 2: max_cart_qty delta (if values differ) → LOW confidence
Priority 3: in_stock transitions (Instamart) → LOW confidence
Priority 4: No signal → estimated=0, LOW
```

## Gurugram Pincodes

18 total, 8 seeds (>80% dark store coverage):
`122001, 122002, 122003, 122008, 122010, 122015, 122018, 122051`
