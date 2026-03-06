# QC Intel — Quick Commerce Intelligence Platform

Multi-agent pipeline for quick commerce market intelligence across **Blinkit**, **Zepto**, and **Swiggy Instamart** in Gurugram. Scrapes product data, estimates daily sales via inventory delta, normalizes products cross-platform, and generates AI-powered category analytics reports.

Built to answer questions like: *"Where is Amul's whitespace in protein drinks? Which price bands are over-indexed? What's moving fastest on Blinkit vs Zepto?"*

## Architecture

```
Scrape (Playwright) → Estimate (morning/night delta) → Normalize (embeddings) → Analyze (Gemini)
```

```
qc-intel/
├── src/
│   ├── agents/scraper/     ← Blinkit, Zepto, Instamart scrapers (Playwright MCP)
│   ├── agents/normalizer.py ← Cross-platform product matching (sentence-transformers + Gemini)
│   ├── agents/analyst.py   ← Market report generation (Gemini)
│   ├── db/                 ← SQLite schema, repository pattern
│   ├── embeddings/         ← product_embedder.py, unit_normalizer.py
│   ├── config/settings.py  ← 18 Gurugram pincodes, platform configs
│   └── orchestrator.py     ← Pipeline coordination
├── api/                    ← FastAPI analytics API
└── web/                    ← Next.js 15 dashboard
```

**Sales estimation**: `estimated_sales = max(morning_qty - night_qty, 0)` — inventory delta between morning and night scrapes.

## Tech Stack

| Layer | Stack |
|-------|-------|
| Scraping | Python, Playwright MCP (headless Chromium/Firefox) |
| AI | Google Gemini 2.5 Flash (normalizer, analyst) |
| Embeddings | `sentence-transformers` (`all-MiniLM-L6-v2`) |
| Storage | SQLite (WAL mode), 6-table entity/observation schema |
| API | FastAPI + uvicorn |
| Dashboard | Next.js 15, React, Tailwind CSS v4, Chart.js |

## Setup

**Prerequisites**: Python 3.12+, Node.js 20+, pnpm, npx

```bash
# Clone
git clone https://github.com/ManmohanBuildsProducts/qc-intel.git
cd qc-intel

# Python env
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Environment
cp .env.example .env
# Edit .env — add your GOOGLE_API_KEY

# Initialize DB
python -c "from src.db.init_db import init_db; import sqlite3; init_db(sqlite3.connect('data/qc_intel.db'))"

# Run tests (184 tests)
pytest tests/ -q
```

## Usage

```bash
# Seed demo data (fixture products + pre-generated reports)
python analyze.py --demo

# Scrape live data
python analyze.py --scrape --morning           # Morning scrape
python analyze.py --scrape --night             # Night scrape

# Calculate sales from delta
python analyze.py --calculate-sales --date 2026-03-06

# Normalize cross-platform products
python analyze.py --normalize --category "Dairy & Bread"

# Generate market intelligence report
python analyze.py --analyze --brand "Amul" --category "Dairy & Bread"

# Full pipeline (scrape + estimate + normalize + analyze)
python analyze.py --full-pipeline
```

## Dashboard

```bash
# Seed demo data first
python analyze.py --demo

# Start API (terminal 1)
uvicorn api.main:app --reload --port 8000

# Start frontend (terminal 2)
cd web && pnpm install && pnpm dev

# Open http://localhost:3000
```

## Data Model

| Table | Purpose |
|-------|---------|
| `product_catalog` | Stable product identity per platform |
| `product_observations` | Daily price/stock snapshots (morning + night) |
| `daily_sales` | Computed sales estimates with confidence scores |
| `canonical_products` | Cross-platform normalized entities |
| `product_mappings` | Catalog → canonical relationships |
| `scrape_runs` | Provenance metadata |

## How Scraping Works

Each platform scraper uses **Playwright MCP** with deterministic parsing — no LLM in the scraping loop:

- **Blinkit**: Sets location cookies → searches product categories → parses accessibility snapshot (button element format)
- **Zepto**: Sets localStorage position → triggers "Select Location" → parses link element format with pvid extraction
- **Instamart**: Uses Chromium (WAF-resistant) → calls `POST /api/instamart/search/v2` from page context → fallback to snapshot

## Coverage

- **Pincodes**: 18 Gurugram pincodes (`122001`–`122102`)
- **Categories**: Dairy & Bread, Fruits & Vegetables, Snacks & Munchies
- **Platforms**: Blinkit, Zepto, Swiggy Instamart

## License

MIT — see [LICENSE](LICENSE)
