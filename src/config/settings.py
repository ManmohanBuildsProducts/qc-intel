"""Configuration for QC Intel — pincodes, platforms, scraping, embeddings."""

import random
from dataclasses import dataclass

from pydantic_settings import BaseSettings


@dataclass(frozen=True)
class PincodeLocation:
    pincode: str
    lat: float
    lng: float
    area: str


# All 18 Gurugram pincodes with approximate center coordinates
GURUGRAM_PINCODES: list[PincodeLocation] = [
    PincodeLocation("122001", 28.4595, 77.0266, "Civil Lines, Sector 14, Sadar Bazar"),
    PincodeLocation("122002", 28.4729, 77.0820, "DLF Phase 1-2, MG Road, Cyber City"),
    PincodeLocation("122003", 28.4600, 77.0700, "Sector 4, 7, 9, DLF Phase 3"),
    PincodeLocation("122004", 28.4500, 77.0700, "Sector 28, 29, Golf Course Road"),
    PincodeLocation("122006", 28.4800, 77.0300, "Palam Vihar, Sector 23"),
    PincodeLocation("122007", 28.4600, 77.0400, "Sector 10, 10A"),
    PincodeLocation("122008", 28.4300, 77.0600, "Sector 45, 46, 47"),
    PincodeLocation("122009", 28.4100, 77.0500, "Sohna Road, Sector 49, 50"),
    PincodeLocation("122010", 28.4700, 77.0700, "DLF Phase 3, Udyog Vihar 4-5"),
    PincodeLocation("122011", 28.4200, 77.0800, "Sector 56, 57, 58"),
    PincodeLocation("122015", 28.4900, 77.0700, "Sector 18, Udyog Vihar 1-3"),
    PincodeLocation("122016", 28.4600, 77.0500, "Sector 31, 32, 33"),
    PincodeLocation("122017", 28.4800, 77.0200, "Palam Vihar Extension, Sector 8"),
    PincodeLocation("122018", 28.4400, 77.0500, "Sector 47-49, Huda City Centre"),
    PincodeLocation("122021", 28.3600, 76.9400, "Manesar, Industrial belt"),
    PincodeLocation("122022", 28.4550, 77.0350, "Sector 17B, Jacobpura"),
    PincodeLocation("122051", 28.4100, 77.0200, "Sector 65-68, Dwarka Expressway"),
    PincodeLocation("122102", 28.3500, 77.0700, "Sohna Town"),
]

# Recommended seed pincodes (>80% dark store coverage)
SEED_PINCODES = ["122001", "122002", "122003", "122008", "122010", "122015", "122018", "122051"]

# Default scrape categories
DEFAULT_CATEGORIES = ["Dairy & Bread", "Fruits & Vegetables", "Snacks & Munchies"]

# User agents for rotation  # noqa: E501
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    " (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    " (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
    " (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15"
    " (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
]


def get_pincode_location(pincode: str) -> PincodeLocation | None:
    """Look up lat/lng for a Gurugram pincode."""
    for loc in GURUGRAM_PINCODES:
        if loc.pincode == pincode:
            return loc
    return None


def get_random_user_agent() -> str:
    """Return a random user agent string."""
    return random.choice(USER_AGENTS)


class Settings(BaseSettings):
    """Application settings, configurable via env vars."""

    # Database
    db_path: str = "data/qc_intel.db"
    db_busy_timeout: int = 5000

    # Scraping
    scrape_delay_min: float = 1.0
    scrape_delay_max: float = 3.0
    scrape_max_retries: int = 3
    scrape_timeout: int = 30
    scrape_max_agent_turns: int = 15

    # Embeddings
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_similarity_threshold: float = 0.85
    embedding_batch_size: int = 64

    # Claude API
    anthropic_api_key: str = ""
    scraper_model: str = "gemini-2.0-flash"
    normalizer_model: str = "claude-sonnet-4-6"
    analyst_model: str = "gemini-2.0-flash"
    max_budget_scraper: float = 0.50
    max_budget_normalizer: float = 1.00
    max_budget_analyst: float = 3.00

    model_config = {"env_prefix": "QC_", "env_file": ".env"}


# Singleton
settings = Settings()
