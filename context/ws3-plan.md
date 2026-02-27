# WS3: Complete Pipeline — Sales, Normalizer, Analytics, Orchestrator

## DesignOps

- **Complexity:** low
- `diagram_not_required: true` — backend pipeline agents, no UI, follows existing service/repo patterns

## Architecture

Four remaining pipeline stages, three of which touch independent files:

```
Track A: Sales Estimation Service     → src/agents/scraper/ (no touch), new service
Track B: Normalizer Agent             → src/embeddings/, src/agents/normalizer.py
Track C: Analytics Agent              → src/agents/analyst.py
Track D: Orchestrator + CLI (serial)  → src/orchestrator.py, analyze.py (after A+B+C merge)
```

**Model routing** (from CLAUDE.md):
| Agent | Model | Budget |
|-------|-------|--------|
| Normalizer validation | claude-sonnet-4-6 | $1.00/run |
| Analyst | claude-opus-4-6 | $3.00/report |

---

## Track A: Sales Estimation Service

**Files:** `src/agents/scraper/sales_service.py` (new), `tests/test_sales_service.py` (new)

### A1: SalesService class
**What:** Service layer that wraps `SalesRepository.calculate_and_store_daily_sales()` with orchestration logic:
```python
class SalesService:
    def __init__(self, conn: sqlite3.Connection) -> None: ...
    def calculate_daily_sales(self, date: str, pincode: str | None = None) -> dict:
        """Run sales calculation for a date. Returns summary stats."""
    def get_category_sales_summary(self, category: str, date: str) -> list[dict]:
        """Get sales summary grouped by brand for a category."""
```
Uses existing `SalesRepository` + `CatalogRepository`. Returns structured summaries (brand, product count, total estimated sales, avg confidence).
**Test:** Integration test with seeded morning/night observations → verify correct sales calculations.
**Deps:** None

### A2: Tests for SalesService
**What:** Integration tests with real DB:
- `test_calculate_daily_sales`: seed morning+night observations → verify sales records created
- `test_category_sales_summary`: verify brand-level aggregation
- `test_no_observations`: empty DB returns empty summary
- `test_restock_detection`: night > morning → low confidence, restock flag
**Files:** `tests/test_sales_service.py`
**Deps:** A1

---

## Track B: Normalizer Agent

**Files:** `src/embeddings/product_embedder.py`, `src/agents/normalizer.py`, `tests/test_normalizer.py` (new)

### B1: ProductEmbedder
**What:** Wrapper around `sentence-transformers` for product name embeddings:
```python
class ProductEmbedder:
    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None: ...
    def embed(self, texts: list[str]) -> np.ndarray: ...
    def similarity_matrix(self, texts_a: list[str], texts_b: list[str]) -> np.ndarray: ...
    def find_matches(self, query_texts: list[str], corpus_texts: list[str], threshold: float = 0.85) -> list[tuple[int, int, float]]: ...
```
Uses `sentence_transformers.SentenceTransformer`. Cosine similarity via `sklearn.metrics.pairwise.cosine_similarity`.
Composes product name for embedding: `"{brand} {name} {unit_normalized}"`.
**Test:** Embed known similar products → verify similarity > 0.85, dissimilar < 0.5.
**Deps:** None

### B2: NormalizerService
**What:** Service that orchestrates cross-platform product matching:
```python
class NormalizerService:
    def __init__(self, conn: sqlite3.Connection) -> None: ...
    def normalize_category(self, category: str) -> NormalizationResult:
        """Match products across platforms for a category."""
```
Algorithm:
1. Get all unmapped catalog products for category (via `CanonicalRepository.get_unmapped()`)
2. Group by platform
3. For each non-Blinkit platform product, find best Blinkit match via embeddings (Blinkit = anchor)
4. If similarity > threshold → same canonical product
5. If no match → create new canonical product
6. Use Claude (sonnet) for ambiguous matches (similarity 0.70–0.85) as tiebreaker
7. Store canonical products + mappings via `CanonicalRepository`
**Test:** Fixture products should match cross-platform (Amul Taaza across all 3).
**Deps:** B1

### B3: Claude validation for ambiguous matches
**What:** Within `NormalizerService`, a method that calls Claude Sonnet to validate ambiguous product matches:
```python
async def _validate_match_with_claude(self, product_a: CatalogProduct, product_b: CatalogProduct, similarity: float) -> bool:
```
Uses `anthropic.AsyncAnthropic` (direct API, not Agent SDK — this is a single classification call).
Prompt: "Are these the same product? {name_a} ({brand_a}, {unit_a}) vs {name_b} ({brand_b}, {unit_b}). Answer YES or NO."
Model: `claude-haiku-4-5` (cheap classification task per cost-aware patterns — override from sonnet).
**Test:** Mock the API call, verify YES/NO parsing.
**Deps:** B2

### B4: Tests for normalizer
**What:**
- `test_embedder_similar_products`: "Amul Taaza Toned Fresh Milk 500ml" ~ "Amul Taaza Toned Milk 500 ml" > 0.85
- `test_embedder_dissimilar_products`: milk vs bread < 0.5
- `test_normalize_category`: seed all 3 platform fixtures → run normalize → verify canonical products created, mappings exist
- `test_ambiguous_match_claude_validation`: mock Claude call → verify match accepted/rejected
- `test_normalization_result_stats`: verify NormalizationResult counts
**Files:** `tests/test_normalizer.py`
**Deps:** B2, B3

---

## Track C: Analytics Agent

**Files:** `src/agents/analyst.py`, `tests/test_analyst.py` (new)

### C1: AnalyticsService (data preparation)
**What:** Service that queries DB and prepares structured data for Claude:
```python
class AnalyticsService:
    def __init__(self, conn: sqlite3.Connection) -> None: ...
    def prepare_report_data(self, brand: str, category: str) -> dict:
        """Gather all data needed for a brand/category report."""
    def generate_report(self, brand: str, category: str) -> MarketReport:
        """Generate full market intelligence report using Claude Opus."""
```
`prepare_report_data` returns: brand products, competitor products, price comparisons, sales estimates, cross-platform availability, category totals.
**Test:** Verify data preparation with seeded DB.
**Deps:** None

### C2: Claude report generation
**What:** `generate_report()` sends prepared data to Claude Opus for analysis:
- System prompt: "You are a market intelligence analyst for quick commerce in India..."
- 8 report sections: Executive Summary, Brand Overview, Price Analysis, Competitive Landscape, Cross-Platform Availability, Sales Velocity, White Space Analysis, Recommendations
- Output: Markdown report saved to `reports/{brand}_{category}_{date}.md`
- Uses `anthropic.AsyncAnthropic` with streaming (long output).
- Model: `claude-opus-4-6` with adaptive thinking.
**Test:** Mock Claude call, verify report structure has all 8 sections.
**Deps:** C1

### C3: Tests for analytics
**What:**
- `test_prepare_report_data`: seed multi-platform data → verify all sections populated
- `test_generate_report_structure`: mock Claude → verify MarketReport model, 8 sections
- `test_empty_brand`: brand with no data → graceful empty report
**Files:** `tests/test_analyst.py`
**Deps:** C2

---

## Track D: Orchestrator + CLI (serial, after merge)

**Files:** `src/orchestrator.py`, `analyze.py`, `tests/test_orchestrator.py` (new)

### D1: Pipeline orchestrator
**What:** Coordinates the full pipeline:
```python
class PipelineOrchestrator:
    def __init__(self, db_path: str | None = None) -> None: ...
    async def run_scrape(self, platform: Platform, pincode: str, category: str, time_of_day: TimeOfDay) -> ScrapeRun: ...
    def run_sales_calculation(self, date: str, pincode: str | None = None) -> dict: ...
    async def run_normalization(self, category: str) -> NormalizationResult: ...
    async def run_analysis(self, brand: str, category: str) -> MarketReport: ...
    async def run_full_pipeline(self, brand: str, category: str, pincode: str) -> MarketReport: ...
    async def run_demo(self) -> MarketReport: ...
```
`run_demo()` seeds fixture data into DB (skips live scraping), runs sales calc + normalize + analyze.
**Test:** Integration test with fixture data → verify full pipeline completes.
**Deps:** A1, B2, C2

### D2: CLI entry point (analyze.py)
**What:** argparse CLI matching CLAUDE.md spec:
```
python analyze.py --scrape --morning
python analyze.py --scrape --night
python analyze.py --calculate-sales --date 2026-02-27
python analyze.py --normalize --category "Dairy & Bread"
python analyze.py --analyze --brand "Amul" --category "Dairy & Bread"
python analyze.py --demo
python analyze.py --full-pipeline
```
Each flag dispatches to `PipelineOrchestrator` methods.
**Test:** CLI arg parsing test, `--demo` integration test.
**Deps:** D1

### D3: Tests for orchestrator + CLI
**What:**
- `test_demo_pipeline`: run demo → verify report generated
- `test_cli_arg_parsing`: verify all flag combinations parse correctly
- `test_sales_calculation_flow`: seed data → calculate → verify
**Files:** `tests/test_orchestrator.py`
**Deps:** D2

### D4: Update progress
**What:** Update `context/progress.md` with WS3 completion.
**Deps:** All above

---

## Parallelism

```
Track A (sales)  ──┐
Track B (normalizer) ──┼──→ Track D (orchestrator + CLI)
Track C (analytics)──┘
```

Tracks A, B, C are **fully independent** — different files, no shared state. Run in parallel worktrees.
Track D merges all three and builds the orchestrator. Runs on main after merge.

## Verification

```bash
# All tests pass
.venv/bin/python -m pytest tests/ -v --tb=short

# Lint clean
.venv/bin/ruff check src/ tests/

# Demo works end-to-end
python analyze.py --demo

# Import check
python -c "from src.orchestrator import PipelineOrchestrator; print('OK')"
```
