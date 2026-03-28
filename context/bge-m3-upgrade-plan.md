# Plan: BGE-M3 + Reranker Embedding Upgrade

**Created:** 2026-03-28
**Status:** Draft — awaiting approval
**Replaces:** `all-MiniLM-L6-v2` (22M params, 384-dim, local)
**With:** `BAAI/bge-m3` (568M, 1024-dim, dense+sparse) + `BAAI/bge-reranker-v2-m3` (568M, cross-encoder)
**Compute:** All ML on Kaggle free GPU (T4), local reads results only

---

## DesignOps Assessment

- **Complexity:** Low
- `diagram_not_required: true` — backend pipeline swap, no UI/UX changes

---

## Goal & Success Criteria

1. Replace MiniLM with BGE-M3 2-stage retrieval (dense+sparse → rerank)
2. All embedding + reranking compute runs on Kaggle T4 GPU
3. Local normalizer reads pre-computed match results, writes to DB
4. Eval F1 >= 1.000 on fixtures (same or better than current)
5. Rule-based eval: fewer flagged pairs than current 43/2019 (2.1%)
6. All 184 existing tests pass, new tests added for Kaggle pipeline

## Scope

**In:**
- Kaggle notebook for embedding + reranking
- Local Kaggle client script (push/poll/download)
- Refactored `product_embedder.py` → loads pre-computed results
- Refactored `normalizer.py` → consumes reranked scores
- New CLI flag `--embed` for Kaggle trigger
- Updated settings, deps, eval harness
- Threshold re-tuning for BGE-M3 score distribution

**Out:**
- Fine-tuning BGE-M3 (backlog item #1)
- Sparse retrieval as standalone feature (used internally only)
- Dashboard/API changes (scores are internal)
- Oracle VM cron changes (separate follow-up)

## Assumptions & Constraints

- Kaggle API key in `.env` (done)
- Kaggle free tier: 30 hrs/week GPU, 12hr max session
- BGE-M3 + reranker fit in T4 16GB VRAM (~3GB total)
- Product catalog exported as JSON for Kaggle input
- Kaggle output: JSON file with scored pairs (not raw vectors)
- Local machine needs `kaggle` CLI (`pip install kaggle`)
- Thresholds will shift — BGE-M3 scores != MiniLM scores

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Kaggle T4 GPU                         │
│                                                          │
│  1. Load product_catalog.json                            │
│  2. BGE-M3 encode all products (dense + sparse)          │
│  3. Per non-anchor product: cosine sim → top-5 candidates│
│  4. Reranker scores top-5 pairs                          │
│  5. Output: match_results.json                           │
│     [{query_id, corpus_id, dense_sim, sparse_sim,        │
│       rerank_score, query_text, corpus_text}]             │
└──────────────────────┬──────────────────────────────────┘
                       │ kaggle kernels output
                       ▼
┌─────────────────────────────────────────────────────────┐
│                   Local (Mac / Oracle VM)                 │
│                                                          │
│  normalizer.py:                                          │
│    1. Read match_results.json                             │
│    2. Apply rerank_score threshold (calibrated)           │
│    3. Unit mismatch guard (unchanged)                     │
│    4. Best-match-per-product (unchanged)                  │
│    5. Write canonical_products + product_mappings to DB   │
└─────────────────────────────────────────────────────────┘
```

---

## Tasks

### Phase 1: Kaggle Infrastructure (tasks 1-3, parallel)

#### Task 1 — Kaggle CLI setup + auth test
- **Do:** Install `kaggle` package, verify API auth works, create `kaggle/` dir in project
- **Files:** `pyproject.toml` (add kaggle dep), `kaggle/.gitkeep`
- **Test:** `kaggle kernels list --mine` succeeds
- **Deps:** None

#### Task 2 — Kaggle embedding notebook
- **Do:** Create the Kaggle notebook (Python script) that:
  - Reads `product_catalog.json` (uploaded as dataset)
  - Loads `BAAI/bge-m3` via FlagEmbedding
  - Encodes all products (dense + sparse vectors)
  - Groups by category, computes per-category similarity (anchor vs others)
  - Selects top-5 candidates per product (cosine sim floor 0.4)
  - Loads `BAAI/bge-reranker-v2-m3`
  - Reranks all candidate pairs
  - Outputs `match_results.json` with scores
- **Files:** `kaggle/embed_and_rerank.py`
- **Test:** Run locally first with 10-product subset to verify output format
- **Deps:** None

#### Task 3 — Product catalog export script
- **Do:** Script to export unmapped products from SQLite → `product_catalog.json` for Kaggle upload
- **Files:** `src/embeddings/catalog_export.py`
- **Test:** Export, verify JSON schema, round-trip check (IDs preserved)
- **Deps:** None

### Phase 2: Kaggle Client (task 4, depends on 1-3)

#### Task 4 — Kaggle push/poll/download client
- **Do:** Create `src/embeddings/kaggle_client.py`:
  - `push_embedding_job(catalog_json_path)` → pushes notebook + dataset to Kaggle
  - `poll_status(kernel_slug)` → polls until complete/error
  - `download_results(kernel_slug)` → downloads `match_results.json` to `data/embeddings/`
  - `run_embedding_pipeline(category)` → orchestrates export → push → poll → download
- **Files:** `src/embeddings/kaggle_client.py`
- **Test:** Integration test with mock Kaggle API (unit), manual E2E test against real Kaggle
- **Deps:** Tasks 1, 2, 3

### Phase 3: Local Pipeline Refactor (tasks 5-7, parallel after task 4)

#### Task 5 — Refactor ProductEmbedder to load pre-computed results
- **Do:** Replace in-process embedding with result loader:
  - `load_match_results(path)` → reads `match_results.json`
  - `find_matches()` → returns matches from pre-computed rerank scores
  - Keep `compose_product_text()` static method (used by export + eval)
  - Remove `sentence-transformers` and `scikit-learn` from local deps
- **Files:** `src/embeddings/product_embedder.py`
- **Test:** Unit test: load fixture match_results.json, verify find_matches returns correct pairs
- **Deps:** Task 4 (need to know output format)

#### Task 6 — Refactor NormalizerService for 2-stage scores
- **Do:** Update `normalize_category()`:
  - Call `kaggle_client.run_embedding_pipeline()` if no cached results
  - Load match results from `data/embeddings/match_results_{category}.json`
  - Use `rerank_score` instead of raw cosine sim for threshold decisions
  - Recalibrate thresholds: `HIGH_CONFIDENCE_THRESHOLD` and `AMBIGUOUS_LOWER_THRESHOLD` (will tune in Phase 4)
  - Unit mismatch guard stays unchanged
  - `similarity_score` stored in DB = `rerank_score` (not dense sim)
- **Files:** `src/agents/normalizer.py`
- **Test:** Unit test with fixture match results, verify DB writes correct
- **Deps:** Task 5

#### Task 7 — New CLI flag `--embed`
- **Do:** Add `--embed` to `analyze.py` that triggers Kaggle pipeline without normalizing:
  - Export catalog → push to Kaggle → poll → download results
  - Separate from `--normalize` which reads cached results
  - `--normalize` auto-triggers `--embed` if no cached results exist
- **Files:** `analyze.py`, `src/orchestrator.py`
- **Test:** `python analyze.py --embed --category "Dairy & Bread"` completes
- **Deps:** Task 4

### Phase 4: Settings & Deps (task 8, parallel with Phase 3)

#### Task 8 — Update settings and dependencies
- **Do:**
  - `settings.py`: Replace `embedding_model` with `embedding_model: str = "BAAI/bge-m3"`, add `reranker_model: str = "BAAI/bge-reranker-v2-m3"`, add `kaggle_username`, `kaggle_kernel_slug`, `embedding_cache_dir`
  - `pyproject.toml`: Add `kaggle` dep, add `FlagEmbedding` to Kaggle-only deps (not local), remove `sentence-transformers` and `scikit-learn` from main deps
  - `.env`: Add `KAGGLE_USERNAME` (already done)
- **Files:** `src/config/settings.py`, `pyproject.toml`, `.env`
- **Test:** `from src.config.settings import settings` loads without error
- **Deps:** None

### Phase 5: Eval & Threshold Tuning (tasks 9-10, sequential, after Phase 3)

#### Task 9 — Update eval harness for BGE-M3
- **Do:**
  - Strategy 1 (fixture sweep): Must run on Kaggle too (or keep local MiniLM for eval only). Decision: create a small eval-specific Kaggle run with fixture data.
  - Strategy 3 (rule-based): No changes needed — reads DB, not embedder
  - Add new Strategy 4: compare MiniLM vs BGE-M3 scores on same fixture pairs
  - Update threshold sweep range (BGE-M3 reranker scores may be 0.0-1.0 sigmoid, not cosine)
- **Files:** `eval/eval_normalization.py`
- **Test:** `python eval/eval_normalization.py --fast` runs clean
- **Deps:** Tasks 5, 6

#### Task 10 — Threshold calibration + full eval
- **Do:**
  - Run Kaggle embedding on full Dairy & Bread catalog
  - Run eval sweep to find optimal `AMBIGUOUS_LOWER_THRESHOLD` and `HIGH_CONFIDENCE_THRESHOLD` for reranker scores
  - Compare: MiniLM baseline (current report) vs BGE-M3 results
  - Update thresholds in `normalizer.py`
  - Write final eval report to `reports/normalization-eval-bge-m3.md`
- **Files:** `src/agents/normalizer.py` (threshold values), `reports/normalization-eval-bge-m3.md`
- **Test:** F1 >= 1.000 on fixtures, flagged < 2.1% on live data
- **Deps:** Task 9

### Phase 6: Test Updates (task 11, after Phase 3)

#### Task 11 — Update existing tests
- **Do:**
  - `test_normalizer.py` `TestProductEmbedder`: Mock or fixture-based (no live embedding)
  - `test_normalizer.py` `TestNormalizerService`: Mock kaggle_client, use fixture match_results
  - Add new tests:
    - `test_kaggle_client.py`: Mock Kaggle API responses
    - `test_catalog_export.py`: Export/import round-trip
  - Verify all 184 tests still pass
- **Files:** `tests/test_normalizer.py`, `tests/test_kaggle_client.py`, `tests/test_catalog_export.py`
- **Test:** `pytest tests/ -v --tb=short` — all green
- **Deps:** Tasks 5, 6

---

## Parallel Execution Map

```
Phase 1 (parallel):  [T1] [T2] [T3]
                        \   |   /
Phase 2:                 [T4]
                        / | \
Phase 3 (parallel): [T5][T6][T7]   Phase 4: [T8]
                       \  |  /
Phase 5 (sequential):  [T9] → [T10]
Phase 6:               [T11] (parallel with Phase 5)
```

## Risks

| Risk | Mitigation |
|------|------------|
| BGE-M3 reranker scores have different distribution than cosine sim | Task 10 explicitly re-calibrates thresholds |
| Kaggle GPU queue wait time adds minutes to pipeline | Acceptable for batch workflow; not interactive |
| Kaggle API rate limits on frequent push/poll | Add backoff; runs are infrequent (max 2x/day) |
| FlagEmbedding library version drift on Kaggle | Pin version in notebook, test monthly |
| Removing sentence-transformers breaks eval Strategy 1 | Keep as dev dep OR port Strategy 1 to Kaggle |
| Kaggle down / quota exhausted | Cache last match_results.json; normalizer uses stale cache with warning |

## Output Format: match_results.json

```json
{
  "model": "BAAI/bge-m3",
  "reranker": "BAAI/bge-reranker-v2-m3",
  "category": "Dairy & Bread",
  "timestamp": "2026-03-28T14:30:00Z",
  "anchor_platform": "blinkit",
  "matches": [
    {
      "query_id": 1234,
      "query_text": "Amul Taaza Toned Milk 500ml",
      "corpus_id": 5678,
      "corpus_text": "Amul Taaza Toned Fresh Milk 500 ml",
      "dense_score": 0.934,
      "sparse_score": 0.812,
      "rerank_score": 0.967
    }
  ]
}
```
