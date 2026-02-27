# QC Intel — Progress Log

## Current State
- **Last completed:** WS4 (frontend analytics dashboard — FastAPI API + Next.js UI)
- **Next up:** Live scrape testing, deployment, production polish
- **Gate status:** WS4 PASSED
- **Tests:** 183/183 passing (84 WS0/WS1 + 47 WS2 + 36 WS3 + 16 WS4)
- **Lint:** ruff clean on all files (0 errors), TypeScript clean
- **Branch:** main

## Session History

### Session 1 — 2026-02-27 (WS0 + WS1)
- GitHub repo created (private): ManmohanBuildsProducts/qc-intel
- Session management: .gitignore, CLAUDE.md, context/progress.md, context/sessions/
- Project structure: 21 Python files across src/ tree
- pyproject.toml with all deps (claude-agent-sdk, sentence-transformers, pydantic, etc.)
- Pydantic models: ScrapedProduct, CatalogProduct, ProductObservation, SalesEstimate, CanonicalProduct, etc.
- Custom exceptions: QCIntelError hierarchy (ScrapeError, NormalizationError, etc.)
- Config: 18 Gurugram pincodes with lat/lng, platform configs, scraping settings
- SQLite schema: 6 tables, 12 indexes, entity/observation split
- DB init: WAL mode, foreign keys, idempotent
- Repository pattern: CatalogRepository, ObservationRepository, SalesRepository, CanonicalRepository, ScrapeRunRepository
- Unit normalizer: volume (ml/L), weight (g/kg), count (pcs/dozen) — 30 test cases
- Test fixtures: 10 products per platform (Blinkit, Zepto, Instamart)
- conftest.py: shared fixtures (db_session, sample_products, sample_observations)
- Gate Hour 3: PASSED — 84/84 tests, ruff clean, DB initializes, all modules importable

### Session 2 — 2026-02-27 (WS2)
- Response parsers: 3 pure functions mapping platform JSON → ScrapedProduct (Blinkit, Zepto, Instamart)
- ScrapeService: orchestrates parse → upsert catalog → insert observations → manage scrape run
- BaseScraper: abstract class using Claude Agent SDK + Playwright MCP
- Platform scrapers: BlinkitScraper, ZeptoScraper, InstamartScraper with platform-specific prompts/URLs
- Factory: create_scraper(platform) returns correct scraper class
- Exports: full __init__.py with all public symbols
- Tests: 21 parser tests + 6 service tests + 20 agent tests = 47 new tests
- Gate WS2: PASSED — 131/131 tests, ruff clean, imports verified, parsers produce correct output

### Session 3 — 2026-02-27 (WS3)
- **Track A** (parallel agent): SalesService — wraps SalesRepository with orchestration + summaries
- **Track B** (parallel agent): ProductEmbedder (sentence-transformers) + NormalizerService (cross-platform matching via embeddings, Blinkit anchor, Claude validation for ambiguous)
- **Track C** (parallel agent): AnalyticsService — data preparation + Claude Opus report generation (8 sections)
- **Track D** (team lead): PipelineOrchestrator — coordinates all stages + run_demo() with fixture seeding
- **CLI**: analyze.py — argparse with --scrape, --calculate-sales, --normalize, --analyze, --demo, --full-pipeline
- Execution: 3 parallel agents in git worktrees (A, B, C), Track D on main after merge
- Tests: 4 sales tests + 12 normalizer tests + 8 analyst tests + 12 orchestrator/CLI tests = 36 new
- Gate WS3: PASSED — 167/167 tests, ruff clean, all imports verified, demo pipeline seeded + ran

### Session 4 — 2026-02-27 (WS4)
- **Track A** (FastAPI backend): api/ directory with main.py, deps.py, models.py, routers/data.py, routers/charts.py, routers/reports.py
- **Track B** (Next.js frontend): web/ directory with dashboard, reports, and explorer pages
- API endpoints: /brands, /categories, /products (paginated), /dashboard/stats, /charts/price-distribution, /charts/platform-coverage, /charts/brand-share, /reports/generate
- Frontend: dark theme analytics dashboard with Sidebar nav, StatsCards, Chart.js charts (Doughnut, Bar), report generation with react-markdown rendering, data explorer with filters + pagination
- Platform color coding: Blinkit=#F8CB46, Zepto=#7B2FBF, Instamart=#FC8019
- Dependencies added: fastapi, httpx, @tailwindcss/typography, chart.js, react-chartjs-2, react-markdown
- Tests: 16 new API tests (health, brands, categories, products, dashboard stats, charts, reports with mocked Claude)
- Gate WS4: PASSED — 183/183 tests, ruff clean, tsc clean, Next.js build clean
