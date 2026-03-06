"""Platform-specific response parsers — pure functions mapping JSON → ScrapedProduct."""

import hashlib
import json
import logging

from pydantic import ValidationError

from src.models.product import Platform, ScrapedProduct

logger = logging.getLogger(__name__)


def _stable_id(platform: str, name: str, unit: str | None = None) -> str:
    """Generate a stable content-based product ID that survives across scrape runs.

    Uses md5(platform + name + unit) to ensure the same product always maps to
    the same platform_product_id, preventing ON CONFLICT overwrites of unrelated products.
    """
    key = f"{platform}:{name.strip().lower()}:{(unit or '').strip().lower()}"
    return hashlib.md5(key.encode()).hexdigest()[:16]


def parse_blinkit_products(items: list[dict], category: str) -> list[ScrapedProduct]:
    """Parse Blinkit API response items into ScrapedProduct models."""
    products: list[ScrapedProduct] = []
    for item in items:
        try:
            name = item["name"]
            product = ScrapedProduct(
                platform=Platform.BLINKIT,
                platform_product_id=_stable_id("blinkit", name, item.get("unit")),
                name=name,
                brand=item.get("brand"),
                category=category,
                subcategory=item.get("subcategory"),
                unit=item.get("unit"),
                image_url=item.get("image_url"),
                price=item.get("price", 0),
                mrp=item.get("mrp"),
                in_stock=item.get("available", True),
                max_cart_qty=item.get("max_allowed_quantity", 0),
                raw_json=json.dumps(item),
            )
            products.append(product)
        except (ValidationError, KeyError) as e:
            logger.warning("Skipping invalid Blinkit item: %s", e)
    return products


def parse_zepto_products(items: list[dict], category: str) -> list[ScrapedProduct]:
    """Parse Zepto API response items into ScrapedProduct models."""
    products: list[ScrapedProduct] = []
    for item in items:
        try:
            images = item.get("images", [])
            image_url = images[0] if images else None
            name = item["name"]
            product = ScrapedProduct(
                platform=Platform.ZEPTO,
                platform_product_id=_stable_id("zepto", name, item.get("unit_quantity")),
                name=name,
                brand=item.get("brand_name"),
                category=category,
                subcategory=item.get("subcategory"),
                unit=item.get("unit_quantity"),
                image_url=image_url,
                price=item.get("discounted_price", 0),
                mrp=item.get("mrp"),
                in_stock=item.get("in_stock", True),
                max_cart_qty=item.get("max_cart_quantity", 0),
                raw_json=json.dumps(item),
            )
            products.append(product)
        except (ValidationError, KeyError) as e:
            logger.warning("Skipping invalid Zepto item: %s", e)
    return products


def parse_instamart_products(items: list[dict], category: str) -> list[ScrapedProduct]:
    """Parse Swiggy Instamart API response items into ScrapedProduct models."""
    products: list[ScrapedProduct] = []
    for item in items:
        try:
            images = item.get("images", [])
            image_url = images[0] if images else None
            name = item["name"]
            product = ScrapedProduct(
                platform=Platform.INSTAMART,
                platform_product_id=_stable_id("instamart", name, item.get("packSize")),
                name=name,
                brand=item.get("brand"),
                category=category,
                subcategory=item.get("subcategory"),
                unit=item.get("packSize"),
                image_url=image_url,
                price=item.get("price", 0),
                mrp=item.get("totalPrice"),
                in_stock=item.get("inStock", True),
                max_cart_qty=item.get("maxSelectableQuantity", 0),
                raw_json=json.dumps(item),
            )
            products.append(product)
        except (ValidationError, KeyError) as e:
            logger.warning("Skipping invalid Instamart item: %s", e)
    return products
