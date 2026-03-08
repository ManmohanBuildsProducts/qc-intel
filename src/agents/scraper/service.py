"""Scrape service — orchestrates parsing, catalog upsert, and observation persistence."""

import logging
import sqlite3
from datetime import datetime
from uuid import uuid4

from src.db.repository import CatalogRepository, ObservationRepository, ScrapeRunRepository
from src.models.product import (
    CatalogProduct,
    Platform,
    ProductObservation,
    ScrapeRun,
    ScrapeRunStatus,
    TimeOfDay,
)

from .parsers import parse_blinkit_products, parse_instamart_products, parse_zepto_products

logger = logging.getLogger(__name__)

PLATFORM_PARSERS = {
    Platform.BLINKIT: parse_blinkit_products,
    Platform.ZEPTO: parse_zepto_products,
    Platform.INSTAMART: parse_instamart_products,
}


class ScrapeService:
    """Orchestrates: parse raw JSON → upsert catalog → create observations → manage scrape run."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.catalog_repo = CatalogRepository(conn)
        self.observation_repo = ObservationRepository(conn)
        self.run_repo = ScrapeRunRepository(conn)

    def process_scrape_results(
        self,
        raw_items: list[dict],
        platform: Platform,
        pincode: str,
        category: str,
        time_of_day: TimeOfDay,
    ) -> ScrapeRun:
        """Parse raw JSON, upsert catalog, create observations, return completed ScrapeRun."""
        run_id = str(uuid4())
        run = ScrapeRun(
            id=run_id,
            platform=platform,
            pincode=pincode,
            category=category,
            time_of_day=time_of_day,
            started_at=datetime.now(),
            status=ScrapeRunStatus.RUNNING,
        )
        self.run_repo.create_run(run)

        parser = PLATFORM_PARSERS[platform]
        scraped = parser(raw_items, category)

        products_saved = 0
        errors = 0

        for product in scraped:
            try:
                catalog_product = CatalogProduct(
                    platform=product.platform,
                    platform_product_id=product.platform_product_id,
                    name=product.name,
                    brand=product.brand,
                    category=product.category,
                    subcategory=product.subcategory,
                    unit=product.unit,
                    image_url=product.image_url,
                )
                catalog_id = self.catalog_repo.upsert_product(catalog_product)

                observation = ProductObservation(
                    catalog_id=catalog_id,
                    scrape_run_id=run_id,
                    pincode=pincode,
                    price=product.price,
                    mrp=product.mrp,
                    in_stock=product.in_stock,
                    max_cart_qty=product.max_cart_qty,
                    inventory_count=product.inventory_count,
                    time_of_day=time_of_day,
                    raw_json=product.raw_json,
                )
                self.observation_repo.insert_observation(observation)
                products_saved += 1
            except Exception:
                logger.exception("Error processing product %s", product.platform_product_id)
                errors += 1

        self.run_repo.complete_run(run_id, products_found=products_saved, errors=errors)

        return ScrapeRun(
            id=run_id,
            platform=platform,
            pincode=pincode,
            category=category,
            time_of_day=time_of_day,
            started_at=run.started_at,
            completed_at=datetime.now(),
            products_found=products_saved,
            errors=errors,
            status=ScrapeRunStatus.COMPLETED,
        )
