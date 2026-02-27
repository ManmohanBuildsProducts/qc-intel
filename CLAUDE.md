# QC Intel — Quick Commerce Intelligence Platform

## Overview

Multi-agent pipeline for quick commerce market intelligence across Blinkit, Zepto, and Swiggy Instamart in Gurugram. Scrapes product data, estimates daily sales via inventory delta, normalizes products cross-platform, and generates category analytics reports.

## Architecture

```
Scrape (Playwright MCP) → Estimate (morning/night delta) → Normalize (embeddings + Claude) → Analyze (Claude Opus)
```

**Agents** (all Claude Agent SDK):
- **Scraper agents** (×3): Platform-specific, Playwright MCP, XHR interception
- **Normalizer agent**: sentence-transformers embeddings + Claude validation
- **Analytics agent**: Claude Opus, generates 8-section market reports

## Tech Stack

**Backend:**
- Python 3.12+, Pydantic v2
- Claude Agent SDK (`claude-agent-sdk`) + Anthropic SDK
- Playwright MCP (headless Firefox)
- `sentence-transformers` (`all-MiniLM-L6-v2`) for embeddings
- SQLite (WAL mode) for time-series data
- `numpy` + `scikit-learn` for cosine similarity
- FastAPI + uvicorn (analytics dashboard API)
- `pytest` + `pytest-asyncio` for testing

**Frontend:**
- Next.js 15 (App Router) + React + TypeScript
- Tailwind CSS v4 + `@tailwindcss/typography`
- Chart.js + `react-chartjs-2` for visualizations
- `react-markdown` for report rendering
- pnpm package manager

## Data Model

Entity/observation split:
- `product_catalog` — stable product identity per platform
- `product_observations` — daily price/stock snapshots (morning + night)
- `daily_sales` — computed from observation pairs with confidence scoring
- `canonical_products` — cross-platform normalized entities
- `product_mappings` — catalog → canonical relationships
- `scrape_runs` — provenance metadata

## Conventions

- **DB access**: Always via repository pattern (`src/db/repository.py`), never raw SQL elsewhere (exception: read-only chart aggregations in `api/routers/charts.py`)
- **Data contracts**: All data flows through Pydantic models (`src/models/`)
- **Exceptions**: Custom hierarchy rooted at `QCIntelError` (`src/models/exceptions.py`)
- **Logging**: `logging` module, structured — no `print()` statements
- **Tests**: Fixture-based, deterministic sample data in `tests/fixtures/`
- **Type hints**: All functions, enforced by ruff
- **Scraping**: XHR interception via Playwright, not DOM scraping

## Key Commands

```bash
# Run all tests (183 tests: 167 pipeline + 16 API)
pytest tests/ -v --tb=short

# Lint
ruff check src/ api/ tests/

# TypeScript check
cd web && pnpm tsc --noEmit

# CLI
python analyze.py --scrape --morning          # Morning scrape run
python analyze.py --scrape --night            # Night scrape run
python analyze.py --calculate-sales --date YYYY-MM-DD
python analyze.py --normalize --category "Dairy & Bread"
python analyze.py --analyze --brand "Amul" --category "Dairy & Bread"
python analyze.py --demo                      # Full demo with sample data
python analyze.py --full-pipeline             # Everything end-to-end

# Dashboard (requires demo data seeded first)
python analyze.py --demo                      # Seed fixture data
uvicorn api.main:app --reload --port 8000     # Start API server
cd web && pnpm dev                            # Start frontend (separate terminal)
# → Dashboard at http://localhost:3000
```

## Project Structure

```
src/                        — Core pipeline
├── agents/scraper/         — Platform-specific scraper agents
├── agents/                 — normalizer.py, analyst.py
├── db/                     — schema.sql, init_db.py, repository.py
├── embeddings/             — product_embedder.py, unit_normalizer.py
├── config/                 — settings.py (pincodes, platform configs)
├── models/                 — Pydantic models, exceptions
└── orchestrator.py         — Pipeline coordination
api/                        — FastAPI analytics API
├── main.py                 — App + CORS + router mounting
├── deps.py                 — DB connection dependency
├── models.py               — API response Pydantic models
└── routers/                — data.py, charts.py, reports.py
web/                        — Next.js 15 dashboard
├── src/app/                — Pages (dashboard, reports, explorer)
├── src/components/         — Sidebar, StatsCard, charts, FilterBar, etc.
├── src/lib/api.ts          — API client
└── src/types/index.ts      — TypeScript interfaces
tests/
├── fixtures/               — Sample JSON per platform
├── conftest.py             — Shared test fixtures
├── test_api.py             — FastAPI endpoint tests (16 tests)
└── test_*.py               — Pipeline tests (167 tests)
```

## Resuming Work

1. Read `context/progress.md` — current state, what's done, what's next
2. Read latest file in `context/sessions/` — detailed notes from last session
3. Run `pytest tests/ -v --tb=short` — verify nothing is broken
4. Check `git log --oneline -10` — recent commits
5. Pick up from "Next up" in progress.md

## Model Routing

| Agent | Model | Budget |
|-------|-------|--------|
| Scraper | `claude-haiku-4-5` | $0.50/run |
| Normalizer validation | `claude-sonnet-4-6` | $1.00/run |
| Quality eval | `claude-opus-4-6` | $1.00/run |
| Analyst | `claude-opus-4-6` | $3.00/report |

## Sales Estimation

`estimated_sales = max(morning_qty - night_qty, 0)`

| Condition | Confidence |
|-----------|-----------|
| morning > night | `high` |
| morning == night | `medium` |
| night > morning (restock) | `low`, restock_flag=1 |
| Missing snapshot | `no_data` |
