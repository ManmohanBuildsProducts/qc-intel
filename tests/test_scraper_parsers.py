"""Tests for platform-specific response parsers."""

import json

from src.agents.scraper.parsers import (
    parse_blinkit_products,
    parse_instamart_products,
    parse_zepto_products,
)
from src.models.product import Platform


class TestBlinkitParser:
    def test_parse_all_products(self, blinkit_fixture_data: list[dict]) -> None:
        products = parse_blinkit_products(blinkit_fixture_data, "Dairy & Bread")
        assert len(products) == 10

    def test_platform_set(self, blinkit_fixture_data: list[dict]) -> None:
        products = parse_blinkit_products(blinkit_fixture_data, "Dairy & Bread")
        assert all(p.platform == Platform.BLINKIT for p in products)

    def test_field_mapping(self, blinkit_fixture_data: list[dict]) -> None:
        products = parse_blinkit_products(blinkit_fixture_data, "Dairy & Bread")
        first = products[0]
        # Real product ID from fixture (str of integer id)
        assert first.platform_product_id == "39868"
        assert first.name == "Amul Taaza Toned Fresh Milk"
        assert first.brand == "Amul"
        assert first.unit == "500 ml"
        assert first.price == 29.0
        assert first.mrp == 30.0
        assert first.in_stock is True
        assert first.max_cart_qty == 5
        assert first.image_url == "https://cdn.blinkit.com/amul-taaza-500ml.jpg"
        assert first.category == "Dairy & Bread"

    def test_oos_product(self, blinkit_fixture_data: list[dict]) -> None:
        products = parse_blinkit_products(blinkit_fixture_data, "Dairy & Bread")
        nestle = [p for p in products if p.brand == "Nestle"][0]
        assert nestle.in_stock is False
        assert nestle.max_cart_qty == 0

    def test_raw_json_stored(self, blinkit_fixture_data: list[dict]) -> None:
        products = parse_blinkit_products(blinkit_fixture_data, "Dairy & Bread")
        assert products[0].raw_json is not None
        parsed = json.loads(products[0].raw_json)
        assert parsed["id"] == 39868

    def test_category_override(self, blinkit_fixture_data: list[dict]) -> None:
        products = parse_blinkit_products(blinkit_fixture_data, "Custom Category")
        assert all(p.category == "Custom Category" for p in products)


class TestZeptoParser:
    def test_parse_all_products(self, zepto_fixture_data: list[dict]) -> None:
        products = parse_zepto_products(zepto_fixture_data, "Dairy & Bread")
        assert len(products) == 10

    def test_platform_set(self, zepto_fixture_data: list[dict]) -> None:
        products = parse_zepto_products(zepto_fixture_data, "Dairy & Bread")
        assert all(p.platform == Platform.ZEPTO for p in products)

    def test_field_mapping(self, zepto_fixture_data: list[dict]) -> None:
        products = parse_zepto_products(zepto_fixture_data, "Dairy & Bread")
        first = products[0]
        # Real product ID from fixture (pvid string)
        assert first.platform_product_id == "z-31001"
        assert first.name == "Amul Taaza Toned Milk"
        assert first.brand == "Amul"  # brand_name → brand
        assert first.unit == "500 ml"  # unit_quantity → unit
        assert first.price == 29.0  # discounted_price → price
        assert first.mrp == 30.0
        assert first.in_stock is True
        assert first.max_cart_qty == 5  # max_cart_quantity → max_cart_qty
        assert first.image_url == "https://cdn.zepto.com/amul-taaza-500ml.jpg"  # images[0]

    def test_raw_json_stored(self, zepto_fixture_data: list[dict]) -> None:
        products = parse_zepto_products(zepto_fixture_data, "Dairy & Bread")
        parsed = json.loads(products[0].raw_json)
        assert parsed["product_id"] == "z-31001"


class TestInstamartParser:
    def test_parse_all_products(self, instamart_fixture_data: list[dict]) -> None:
        products = parse_instamart_products(instamart_fixture_data, "Dairy & Bread")
        assert len(products) == 10

    def test_platform_set(self, instamart_fixture_data: list[dict]) -> None:
        products = parse_instamart_products(instamart_fixture_data, "Dairy & Bread")
        assert all(p.platform == Platform.INSTAMART for p in products)

    def test_field_mapping(self, instamart_fixture_data: list[dict]) -> None:
        products = parse_instamart_products(instamart_fixture_data, "Dairy & Bread")
        first = products[0]
        # Real product ID from fixture
        assert first.platform_product_id == "im-5001"
        assert first.name == "Amul Taaza Homogenised Toned Milk"
        assert first.brand == "Amul"
        assert first.unit == "500 ml"  # packSize → unit
        assert first.price == 29.0
        assert first.mrp == 30.0  # totalPrice → mrp
        assert first.in_stock is True  # inStock → in_stock
        assert first.max_cart_qty == 5  # maxSelectableQuantity → max_cart_qty
        assert first.image_url == "https://cdn.swiggy.com/amul-taaza-500ml.jpg"  # images[0]

    def test_oos_product(self, instamart_fixture_data: list[dict]) -> None:
        products = parse_instamart_products(instamart_fixture_data, "Dairy & Bread")
        oos = [p for p in products if not p.in_stock]
        assert len(oos) == 1
        assert oos[0].name == "Modern Multigrain Bread"
        assert oos[0].max_cart_qty == 0

    def test_raw_json_stored(self, instamart_fixture_data: list[dict]) -> None:
        products = parse_instamart_products(instamart_fixture_data, "Dairy & Bread")
        parsed = json.loads(products[0].raw_json)
        assert parsed["id"] == "im-5001"


class TestParserEdgeCases:
    def test_empty_list(self) -> None:
        assert parse_blinkit_products([], "Dairy") == []
        assert parse_zepto_products([], "Dairy") == []
        assert parse_instamart_products([], "Dairy") == []

    def test_zero_price_item_skipped(self) -> None:
        items = [{"id": 1, "name": "Free Item", "price": 0, "available": True}]
        products = parse_blinkit_products(items, "Dairy")
        assert len(products) == 0

    def test_missing_optional_fields(self) -> None:
        items = [{"id": 1, "name": "Minimal Item", "price": 10.0}]
        products = parse_blinkit_products(items, "Dairy")
        assert len(products) == 1
        assert products[0].brand is None
        assert products[0].unit is None
        assert products[0].image_url is None

    def test_missing_required_field_skipped(self) -> None:
        # Missing 'name' key
        items = [{"id": 1, "price": 10.0}]
        products = parse_blinkit_products(items, "Dairy")
        assert len(products) == 0

    def test_zepto_missing_images(self) -> None:
        items = [{"product_id": "z-1", "name": "No Image", "discounted_price": 10.0}]
        products = parse_zepto_products(items, "Dairy")
        assert len(products) == 1
        assert products[0].image_url is None

    def test_instamart_zero_price_skipped(self) -> None:
        items = [{"id": "im-1", "name": "Free", "price": 0, "totalPrice": 0}]
        products = parse_instamart_products(items, "Dairy")
        assert len(products) == 0
