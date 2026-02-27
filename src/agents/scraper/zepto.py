"""Zepto scraper agent — XHR interception for Zepto's product API."""

from src.models.product import Platform

from .base import BaseScraper


class ZeptoScraper(BaseScraper):
    """Scraper for Zepto quick commerce platform."""

    def __init__(self, conn):
        super().__init__(Platform.ZEPTO, conn)

    def get_system_prompt(self) -> str:
        return (
            "You are a web scraping agent for Zepto (zepto.co). "
            "Your job is to extract product data from Zepto's API responses.\n\n"
            "Instructions:\n"
            "1. Navigate to the provided Zepto URL\n"
            "2. Zepto requires a store_id to be set first — this comes from the location/pincode selection\n"
            "3. Monitor network requests for API calls to /api/v3/search or /api/v4/catalog endpoints\n"
            "4. The store_id is typically set via a location selection API call\n"
            "5. Extract the products array from the API response JSON\n"
            "6. Return ONLY the raw JSON array of product objects\n\n"
            "Expected product fields: product_id, name, brand_name, category, subcategory, "
            "unit_quantity, discounted_price, mrp, in_stock, max_cart_quantity, images"
        )

    def get_scrape_url(self, pincode: str, category: str) -> str:
        category_slug = category.lower().replace(" & ", "-").replace(" ", "-")
        return f"https://www.zepto.co/cn/{category_slug}?pincode={pincode}"
