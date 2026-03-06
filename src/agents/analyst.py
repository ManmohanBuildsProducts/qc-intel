"""Analytics agent — market intelligence report generation."""

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from google import genai

from src.config.settings import settings
from src.db.repository import CanonicalRepository, CatalogRepository, ObservationRepository, SalesRepository
from src.models.product import MarketReport

logger = logging.getLogger(__name__)

REPORT_SECTIONS = [
    "Executive Summary",
    "Brand Overview",
    "Price Analysis",
    "Competitive Landscape",
    "Cross-Platform Availability",
    "Sales Velocity",
    "White Space Analysis",
    "Recommendations",
]

SYSTEM_PROMPT = (
    "You are a market intelligence analyst specializing in India's quick commerce sector.\n"
    "You analyze data from Blinkit, Zepto, and Swiggy Instamart to provide actionable insights.\n\n"
    "Generate a comprehensive market intelligence report with exactly these 8 sections:\n"
    "1. Executive Summary\n"
    "2. Brand Overview\n"
    "3. Price Analysis\n"
    "4. Competitive Landscape\n"
    "5. Cross-Platform Availability\n"
    "6. Sales Velocity\n"
    "7. White Space Analysis\n"
    "8. Recommendations\n\n"
    "Format as Markdown with ## headers for each section. Be specific with numbers and data points.\n"
    "If data is limited, note the limitation but still provide analysis based on available information."
)

OPPORTUNITY_SYSTEM_PROMPT = (
    "You are a market intelligence analyst specializing in India's quick commerce sector.\n"
    "You analyze data from Blinkit, Zepto, and Swiggy Instamart to identify market opportunities.\n\n"
    "A brand has asked: 'What are the opportunities and white spaces for us in this category on quick commerce?'\n"
    "The brand is NOT yet listed on these platforms (or has very limited presence).\n"
    "Use the competitive landscape data to identify gaps, underserved segments, and entry strategies.\n\n"
    "Generate a market opportunity report with exactly these 8 sections:\n"
    "1. Executive Summary\n"
    "2. Brand Overview\n"
    "3. Price Analysis\n"
    "4. Competitive Landscape\n"
    "5. Cross-Platform Availability\n"
    "6. Sales Velocity\n"
    "7. White Space Analysis\n"
    "8. Recommendations\n\n"
    "For sections where direct brand data is unavailable, analyze the GAPS in the market "
    "that this brand could fill. Sections 7 (White Space Analysis) and 8 (Recommendations) "
    "must be especially detailed — identify specific price bands, pack sizes, platforms, and "
    "segments that are underserved by current players. Be specific with numbers and data points. "
    "Format as Markdown with ## headers."
)


class AnalyticsService:
    """Generates market intelligence reports using Claude."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.catalog_repo = CatalogRepository(conn)
        self.sales_repo = SalesRepository(conn)
        self.canonical_repo = CanonicalRepository(conn)
        self.observation_repo = ObservationRepository(conn)

    def prepare_report_data(self, brand: str, category: str) -> dict:
        """Gather all data needed for a brand/category report."""
        brand_products = self.catalog_repo.get_by_brand(brand)
        brand_in_category = [p for p in brand_products if p.category == category]

        category_products = self.catalog_repo.get_by_category(category)
        competitor_products = [p for p in category_products if p.brand != brand]

        # Platform breakdown
        platforms_present: set[str] = set()
        for p in brand_in_category:
            platforms_present.add(p.platform.value)

        # Get latest observations for price data
        brand_prices: list[dict] = []
        for p in brand_in_category:
            if p.id:
                obs = self.observation_repo.get_latest_for_product(p.id, "122001")
                if obs:
                    brand_prices.append({
                        "name": p.name,
                        "platform": p.platform.value,
                        "price": obs.price,
                        "mrp": obs.mrp,
                        "in_stock": obs.in_stock,
                    })

        # Competitor prices — more data for opportunity mode
        competitor_prices: list[dict] = []
        for p in competitor_products[:50]:
            if p.id:
                obs = self.observation_repo.get_latest_for_product(p.id, "122001")
                if obs:
                    competitor_prices.append({
                        "name": p.name,
                        "brand": p.brand,
                        "platform": p.platform.value,
                        "price": obs.price,
                        "mrp": obs.mrp,
                    })

        # Cross-platform view
        cross_platform = self.canonical_repo.get_cross_platform_view()
        brand_cross_platform = [cp for cp in cross_platform if cp.get("brand") == brand]

        return {
            "brand": brand,
            "category": category,
            "brand_products": [
                {"name": p.name, "platform": p.platform.value, "unit": p.unit}
                for p in brand_in_category
            ],
            "brand_product_count": len(brand_in_category),
            "platforms_present": sorted(platforms_present),
            "total_category_products": len(category_products),
            "competitor_brands": sorted(set(p.brand for p in competitor_products if p.brand)),
            "brand_prices": brand_prices,
            "competitor_prices": competitor_prices,
            "cross_platform_products": brand_cross_platform,
        }

    async def generate_report(self, brand: str, category: str) -> MarketReport:
        """Generate full market intelligence report using Gemini."""
        data = self.prepare_report_data(brand, category)
        is_opportunity_mode = data["brand_product_count"] == 0

        system_prompt = OPPORTUNITY_SYSTEM_PROMPT if is_opportunity_mode else SYSTEM_PROMPT
        user_message = self._format_data_for_gemini(data)

        client = genai.Client(api_key=settings.google_api_key)
        response = await client.aio.models.generate_content(
            model=settings.analyst_model,
            contents=user_message,
            config=genai.types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=4096,
            ),
        )
        report_content = response.text or ""
        report_path = self._save_report(brand, category, report_content)

        return MarketReport(
            brand=brand,
            category=category,
            report_path=report_path,
            sections=REPORT_SECTIONS,
            product_count=data["brand_product_count"],
            platform_count=len(data["platforms_present"]),
        )

    def _format_data_for_gemini(self, data: dict) -> str:
        """Format report data as a structured prompt for Gemini."""
        is_opportunity = data["brand_product_count"] == 0
        if is_opportunity:
            intro = (
                f"Analyze market entry opportunities for **{data['brand']}** "
                f"in the **{data['category']}** category on Blinkit, Zepto, and Swiggy Instamart.\n"
                f"**{data['brand']}** has NO current listings in this category. "
                f"Use the competitor data below to identify gaps and opportunities."
            )
        else:
            intro = (
                f"Generate a market intelligence report for **{data['brand']}** "
                f"in the **{data['category']}** category."
            )

        lines = [
            intro,
            "\n### Category Overview",
            f"- Total products in category: {data['total_category_products']}",
            f"- Active brands: {len(data['competitor_brands']) + (1 if not is_opportunity else 0)}",
            f"- Competitor brands: {', '.join(data['competitor_brands'][:15])}",
        ]

        if not is_opportunity:
            lines += [
                f"\n### {data['brand']} Presence",
                f"- Products listed: {data['brand_product_count']}",
                f"- Platforms present: {', '.join(data['platforms_present'])}",
            ]

        if data["brand_prices"]:
            lines.append(f"\n### {data['brand']} Product Prices")
            for p in data["brand_prices"]:
                stock = "In Stock" if p["in_stock"] else "OOS"
                lines.append(
                    f"- {p['name']} ({p['platform']}): "
                    f"\u20b9{p['price']} (MRP \u20b9{p['mrp']}) [{stock}]"
                )

        if data["competitor_prices"]:
            lines.append("\n### Competitor Products & Prices (full sample)")
            for p in data["competitor_prices"]:
                lines.append(
                    f"- {p['name']} by {p['brand']} ({p['platform']}): \u20b9{p['price']} (MRP \u20b9{p['mrp']})"
                )

        if data["cross_platform_products"]:
            lines.append(f"\n### {data['brand']} Cross-Platform Availability")
            for cp in data["cross_platform_products"]:
                platforms = [pl["platform"] for pl in cp["platforms"]]
                lines.append(f"- {cp['canonical_name']}: {', '.join(platforms)}")

        return "\n".join(lines)

    def _save_report(self, brand: str, category: str, content: str) -> str:
        """Save report to disk and return the path."""
        reports_dir = Path("reports")
        reports_dir.mkdir(exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d")
        slug = f"{brand}_{category}_{date_str}".lower().replace(" ", "_").replace("&", "and")
        path = reports_dir / f"{slug}.md"
        path.write_text(content)
        return str(path)
