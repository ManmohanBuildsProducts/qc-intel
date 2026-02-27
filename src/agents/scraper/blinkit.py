"""Blinkit scraper agent — XHR interception for Blinkit's product API."""

from src.config.settings import get_pincode_location
from src.models.product import Platform

from .base import BaseScraper


class BlinkitScraper(BaseScraper):
    """Scraper for Blinkit (Grofers/Zomato) quick commerce platform."""

    def __init__(self, conn):
        super().__init__(Platform.BLINKIT, conn)

    def get_system_prompt(self) -> str:
        return (
            "You are a web scraping agent for Blinkit (blinkit.com). "
            "Your job is to extract product data from Blinkit's API responses.\n\n"
            "Instructions:\n"
            "1. Navigate to the provided Blinkit URL\n"
            "2. Blinkit uses XHR requests to fetch product listings\n"
            "3. Monitor network requests for API calls to /v2/listing or /v6/listing endpoints\n"
            "4. The request headers must include lat and lon coordinates for the delivery location\n"
            "5. Extract the products array from the API response JSON\n"
            "6. Return ONLY the raw JSON array of product objects\n\n"
            "Expected product fields: id, name, brand, category, subcategory, unit, "
            "price, mrp, available, max_allowed_quantity, image_url"
        )

    def get_scrape_url(self, pincode: str, category: str) -> str:
        location = get_pincode_location(pincode)
        lat = location.lat if location else 28.4595
        lng = location.lng if location else 77.0266
        category_slug = category.lower().replace(" & ", "-").replace(" ", "-")
        return f"https://blinkit.com/cn/{category_slug}?lat={lat}&lon={lng}"
