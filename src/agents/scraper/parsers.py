"""Platform-specific response parsers — pure functions mapping JSON → ScrapedProduct."""

import hashlib
import json
import logging

from pydantic import ValidationError

from src.models.product import Platform, ScrapedProduct

logger = logging.getLogger(__name__)


def _stable_id(platform: str, name: str, unit: str | None = None) -> str:
    """Generate a stable content-based product ID that survives across scrape runs.

    Used as fallback when the platform doesn't provide a real product ID.
    Uses md5(platform + name + unit) to ensure the same product always maps to
    the same platform_product_id, preventing ON CONFLICT overwrites of unrelated products.
    """
    key = f"{platform}:{name.strip().lower()}:{(unit or '').strip().lower()}"
    return hashlib.md5(key.encode()).hexdigest()[:16]


def parse_blinkit_products(items: list[dict], category: str) -> list[ScrapedProduct]:
    """Parse Blinkit API response items into ScrapedProduct models.

    Expects items from /v1/layout/search cart_item objects:
      id (int), name/product_name/display_name, brand, unit, price, mrp,
      inventory (actual stock count), image_url, available/unavailable_quantity.
    """
    products: list[ScrapedProduct] = []
    for item in items:
        try:
            name = (
                item.get("name")
                or item.get("product_name")
                or item.get("display_name")
                or ""
            )
            if not name:
                continue

            # Use real integer product_id when available; fall back to content hash
            raw_id = item.get("id") or item.get("product_id")
            platform_product_id = (
                str(raw_id) if raw_id else _stable_id("blinkit", name, item.get("unit"))
            )

            # available: explicit field OR infer from unavailable_quantity == 0
            if "available" in item:
                in_stock = bool(item["available"])
            elif "unavailable_quantity" in item:
                in_stock = item["unavailable_quantity"] == 0
            else:
                in_stock = True

            product = ScrapedProduct(
                platform=Platform.BLINKIT,
                platform_product_id=platform_product_id,
                name=name,
                brand=item.get("brand"),
                category=category,
                subcategory=item.get("subcategory"),
                unit=item.get("unit"),
                image_url=item.get("image_url"),
                price=float(item.get("price") or 0),
                mrp=item.get("mrp"),
                in_stock=in_stock,
                max_cart_qty=int(item.get("max_allowed_quantity") or item.get("quantity") or 0),
                inventory_count=item.get("inventory"),
                raw_json=json.dumps(item),
            )
            products.append(product)
        except (ValidationError, KeyError, TypeError) as e:
            logger.warning("Skipping invalid Blinkit item: %s", e)
    return products


def parse_zepto_products(items: list[dict], category: str) -> list[ScrapedProduct]:
    """Parse Zepto API response items into ScrapedProduct models.

    Supports both snapshot-parsed items (product_id as pvid string) and
    API-parsed items (product_id as pvid, quantity as real inventory count).
    """
    products: list[ScrapedProduct] = []
    for item in items:
        try:
            images = item.get("images", [])
            image_url = images[0] if images else None
            name = item.get("name") or item.get("product_name") or ""
            if not name:
                continue

            # Use pvid (UUID string) when available; fall back to content hash
            raw_id = item.get("product_id")
            platform_product_id = (
                raw_id if raw_id else _stable_id("zepto", name, item.get("unit_quantity"))
            )

            product = ScrapedProduct(
                platform=Platform.ZEPTO,
                platform_product_id=platform_product_id,
                name=name,
                brand=item.get("brand_name") or item.get("brand"),
                category=category,
                subcategory=item.get("subcategory"),
                unit=item.get("unit_quantity") or item.get("unit"),
                image_url=image_url or item.get("image_url"),
                price=float(item.get("discounted_price") or item.get("price") or 0),
                mrp=item.get("mrp"),
                in_stock=item.get("in_stock", True),
                max_cart_qty=int(item.get("max_cart_quantity") or 0),
                inventory_count=item.get("quantity"),  # real inventory from API
                raw_json=json.dumps(item),
            )
            products.append(product)
        except (ValidationError, KeyError, TypeError) as e:
            logger.warning("Skipping invalid Zepto item: %s", e)
    return products


def parse_instamart_products(items: list[dict], category: str) -> list[ScrapedProduct]:
    """Parse Swiggy Instamart API response items into ScrapedProduct models.

    Supports both API-parsed items (rich, from _extract_from_api_response) and
    snapshot-parsed items (limited, from _extract_from_snapshot).
    """
    products: list[ScrapedProduct] = []
    for item in items:
        try:
            images = item.get("images", [])
            image_url = (
                item.get("image_url")
                or (images[0] if images else None)
            )
            name = item.get("name") or ""
            if not name:
                continue

            raw_id = item.get("id") or item.get("product_id")
            platform_product_id = (
                str(raw_id) if raw_id else _stable_id("instamart", name, item.get("packSize"))
            )

            product = ScrapedProduct(
                platform=Platform.INSTAMART,
                platform_product_id=platform_product_id,
                name=name,
                brand=item.get("brand") or item.get("brand_name"),
                category=category,
                subcategory=item.get("subcategory"),
                unit=item.get("packSize") or item.get("unit"),
                image_url=image_url,
                price=float(item.get("price") or 0),
                mrp=item.get("totalPrice") or item.get("mrp"),
                in_stock=item.get("inStock", item.get("in_stock", True)),
                max_cart_qty=int(item.get("maxSelectableQuantity") or item.get("max_cart_qty") or 0),
                inventory_count=item.get("inventory_count") or item.get("available_quantity"),
                raw_json=json.dumps(item),
            )
            products.append(product)
        except (ValidationError, KeyError, TypeError) as e:
            logger.warning("Skipping invalid Instamart item: %s", e)
    return products
