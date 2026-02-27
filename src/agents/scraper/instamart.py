"""Swiggy Instamart scraper agent — XHR interception for Instamart's product API."""

from src.models.product import Platform

from .base import BaseScraper


class InstamartScraper(BaseScraper):
    """Scraper for Swiggy Instamart quick commerce platform."""

    def __init__(self, conn):
        super().__init__(Platform.INSTAMART, conn)

    def get_system_prompt(self) -> str:
        return (
            "You are a web scraping agent for Swiggy Instamart (instamart.swiggy.com). "
            "Your job is to extract product data from Instamart's API responses.\n\n"
            "Instructions:\n"
            "1. Navigate to the provided Instamart URL\n"
            "2. Instamart uses a tid (transaction ID) and cookie-based session for API auth\n"
            "3. Monitor network requests for API calls to /api/instamart/category or /api/instamart/search\n"
            "4. The tid is typically set during initial page load\n"
            "5. Extract the products array from the API response JSON (usually under data.widgets or similar)\n"
            "6. Return ONLY the raw JSON array of product objects\n\n"
            "Expected product fields: id, name, brand, category, subcategory, packSize, "
            "price, totalPrice, inStock, maxSelectableQuantity, images"
        )

    def get_scrape_url(self, pincode: str, category: str) -> str:
        category_slug = category.lower().replace(" & ", "-").replace(" ", "-")
        return f"https://www.swiggy.com/instamart/category/{category_slug}?pincode={pincode}"
