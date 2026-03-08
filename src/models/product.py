"""Pydantic data models for QC Intel pipeline."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class Platform(StrEnum):
    BLINKIT = "blinkit"
    ZEPTO = "zepto"
    INSTAMART = "instamart"


class TimeOfDay(StrEnum):
    MORNING = "morning"
    NIGHT = "night"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NO_DATA = "no_data"


class ScrapeRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ScrapedProduct(BaseModel):
    """Raw product data from a single platform scrape."""

    platform: Platform
    platform_product_id: str
    name: str
    brand: str | None = None
    category: str
    subcategory: str | None = None
    unit: str | None = None
    image_url: str | None = None
    price: float
    mrp: float | None = None
    in_stock: bool = True
    max_cart_qty: int = 0
    inventory_count: int | None = None
    raw_json: str | None = None

    @field_validator("price")
    @classmethod
    def price_positive(cls, v: float) -> float:
        if v <= 0:
            msg = "price must be positive"
            raise ValueError(msg)
        return v

    @field_validator("max_cart_qty")
    @classmethod
    def max_cart_qty_non_negative(cls, v: int) -> int:
        if v < 0:
            msg = "max_cart_qty must be non-negative"
            raise ValueError(msg)
        return v


class CatalogProduct(BaseModel):
    """Stable product identity in the catalog."""

    id: int | None = None
    platform: Platform
    platform_product_id: str
    name: str
    brand: str | None = None
    category: str
    subcategory: str | None = None
    unit: str | None = None
    image_url: str | None = None
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None


class ProductObservation(BaseModel):
    """A single price/stock observation for a product at a pincode."""

    id: int | None = None
    catalog_id: int
    scrape_run_id: str
    pincode: str
    price: float
    mrp: float | None = None
    in_stock: bool = True
    max_cart_qty: int = 0
    inventory_count: int | None = None
    time_of_day: TimeOfDay
    observed_at: datetime | None = None
    raw_json: str | None = None

    @field_validator("price")
    @classmethod
    def price_positive(cls, v: float) -> float:
        if v <= 0:
            msg = "price must be positive"
            raise ValueError(msg)
        return v

    @field_validator("max_cart_qty")
    @classmethod
    def max_cart_qty_non_negative(cls, v: int) -> int:
        if v < 0:
            msg = "max_cart_qty must be non-negative"
            raise ValueError(msg)
        return v


class SalesEstimate(BaseModel):
    """Daily sales estimate computed from morning/night observation delta."""

    id: int | None = None
    catalog_id: int
    pincode: str
    sale_date: str
    morning_qty: int
    night_qty: int
    estimated_sales: int
    confidence: Confidence
    restock_flag: bool = False


class CanonicalProduct(BaseModel):
    """Cross-platform normalized product entity."""

    id: int | None = None
    canonical_name: str
    brand: str | None = None
    category: str
    unit_normalized: str | None = None
    embedding: bytes | None = None
    created_at: datetime | None = None


class ProductMapping(BaseModel):
    """Mapping from a catalog product to a canonical product."""

    catalog_id: int
    canonical_id: int
    similarity_score: float
    mapped_at: datetime | None = None

    @field_validator("similarity_score")
    @classmethod
    def score_in_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            msg = "similarity_score must be between 0 and 1"
            raise ValueError(msg)
        return v


class ScrapeRun(BaseModel):
    """Metadata for a single scrape batch run."""

    id: str
    platform: Platform
    pincode: str
    category: str
    time_of_day: TimeOfDay
    started_at: datetime | None = None
    completed_at: datetime | None = None
    products_found: int = 0
    errors: int = 0
    status: ScrapeRunStatus = ScrapeRunStatus.RUNNING


class NormalizationResult(BaseModel):
    """Result of normalizing products across platforms."""

    canonical_products_created: int
    mappings_created: int
    unmapped_count: int
    precision: float | None = None
    recall: float | None = None


class MarketReport(BaseModel):
    """Generated market intelligence report metadata."""

    brand: str
    category: str
    generated_at: datetime = Field(default_factory=datetime.now)
    report_path: str
    sections: list[str]
    product_count: int
    platform_count: int
