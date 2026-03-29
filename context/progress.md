# QC Intel — Progress Log

## Current State
- **Last completed:** WS6 (embedding upgrade to bge-m3, Kaggle pipeline, MRP guard, all-category normalization)
- **Next up:** Backlog items in `context/kaggle-backlog.md` (Zepto dedup, LLM judge cleanup, reranker, incremental normalization)
- **Gate status:** WS6 PASSED
- **Tests:** 236/236 passing
- **Lint:** ruff clean on all files (0 errors)
- **Branch:** main
- **Normalization:** 5,822/6,332 products mapped across 9 categories, 5,294 canonicals (91 bad mappings cleaned by LLM judge on 2026-03-29)

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

### Session 5 — 2026-03-06 (WS5: eval + threshold + deployment)
- **Eval harness**: `eval/eval_normalization.py` — 3-strategy automated normalization eval
  - Strategy 1: fixture ground truth sweep (P/R/F1 across 5 thresholds, single embedding pass)
  - Strategy 2: LLM-as-judge on live DB ambiguous pairs (async Gemini, --fix deletes bad mappings)
  - Strategy 3: rule-based (unit conflicts, oversized clusters, low Jaccard)
  - CLI: `--fast`, `--sweep`, `--llm-judge [--fix]`
- **Bug fixes** (`normalizer.py`): `max_output_tokens=10` → 200 for gemini-2.5-flash; guard `response.text or ""`
- **Threshold tuning**: `AMBIGUOUS_LOWER_THRESHOLD` raised 0.70 → 0.80 (eval-backed)
- **DB note**: Live DB has 353 canonicals — extra 62 are legitimate single-platform products, not fragmentation
- **Deployment**: `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `railway.toml`, `.env.example`
- **CORS**: `api/main.py` now reads allowed origins from `QC_ALLOWED_ORIGINS` env var
- **Scraper verification**: 48/48 scraper tests pass
- Gate WS5: PASSED — 184/184 tests, ruff clean, deployment files complete

### Session 6 — 2026-03-28 (WS6: embedding upgrade + normalization)
- **Eval on real data**: Ran normalization eval on existing MiniLM data — F1=1.000 on fixtures, 2.1% flagged
- **Model research**: Evaluated bge-m3, Qwen3-Embedding-0.6B, Vyakyarth (Krutrim), Sarvam (no embedding model)
- **Winner**: BAAI/bge-m3 dense (568M params, 1024-dim) — 25% better recall than MiniLM
- **Kaggle GPU pipeline**: Full end-to-end — export catalog → upload dataset → push kernel → P100 GPU → download results
  - `kaggle/embed_and_rerank.py`: benchmark notebook (4 combos tested)
  - `src/embeddings/catalog_export.py`: DB → JSON for Kaggle
  - `src/embeddings/kaggle_client.py`: push/poll/download client
  - Models uploaded as Kaggle Dataset (offline mode, no internet needed on GPU)
  - New CLI flag: `python analyze.py --embed`
- **MRP guard**: Products with MRP >15% apart rejected as matches (India-specific: MRP is legally fixed by manufacturer)
  - Kills false positives like "Amul Lactose Free Milk ↔ Amul Fresh Cream"
  - MRP tolerance analysis: 15% optimal (5% too aggressive, 20% too loose, plateau at 25-30%)
- **All 9 categories normalized**: 5,913 products → 5,294 canonicals, 100% mapped, 1.5% flagged
- **Dependencies**: Removed `sentence-transformers` and `scikit-learn` from main deps (Kaggle handles ML)
- **New files**: 6 new (kaggle notebook, catalog export, kaggle client, 3 test files)
- **Modified**: normalizer.py, product_embedder.py, settings.py, orchestrator.py, analyze.py, pyproject.toml
- Gate WS6: PASSED — 236/236 tests (52 new), ruff clean, all categories normalized
