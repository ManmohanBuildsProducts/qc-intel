# Kaggle GPU & Pipeline Backlog

Tasks to offload to Kaggle free GPU (30hrs/week T4/P100) and pipeline improvements. Ordered by impact.
Credentials: `.env` (KAGGLE_USERNAME, KAGGLE_KEY).
Compute runs on laptop (no Oracle VM). Kaggle for ML only.

---

## 1. Fine-tune BGE-M3 on Product Pairs

**Priority:** High | **When:** After ~500+ ground truth pairs collected
**Quota:** ~2 hrs/run (monthly)

> Fine-tune BAAI/bge-m3 on QC Intel product matching pairs. Ground truth is in the eval harness (fixture pairs + LLM-judge verified pairs from product_mappings). Use Kaggle T4 GPU. Train with FlagEmbedding's built-in fine-tuning on hard negatives (same brand different variant, same category different product). Export fine-tuned model to Kaggle Dataset. Update the embedding notebook to use fine-tuned weights.

---

## 2. Replace Gemini Match Validation with Open-Source LLM

**Priority:** High | **When:** Anytime (cost savings)
**Quota:** ~10 min/run

> Replace `_validate_match_with_llm` (currently Gemini API, ~$1/run) with an open-source LLM on Kaggle GPU. Candidate models: Qwen2.5-7B-Instruct or Llama-3.1-8B (both fit T4 in int8). Task is binary classification: "are these the same product?" on ambiguous pairs (0.80-0.85 similarity). Benchmark against Gemini's answers as ground truth. If accuracy >= 95%, switch over.

---

## 3. Demand Forecasting on Daily Sales

**Priority:** Medium | **When:** After 2+ weeks of daily_sales data
**Quota:** ~30 min/week

> Build a time-series demand forecasting model on daily_sales data. Kaggle T4 GPU. Input: product-level daily sales estimates + price + platform + category. Output: 7-day sales forecast per canonical product. Start with LightGBM baseline, then try a small transformer (TimesFM or Chronos). Export predictions to `data/forecasts/`. Surface "trending" and "declining" products in the analytics report.

---

## 4. Price Anomaly Detection

**Priority:** Medium | **When:** After stable daily scraping
**Quota:** ~5 min/run (after each scrape)

> Build a price anomaly detector for cross-platform price monitoring. Flag: sudden price spikes/drops (>20% day-over-day), cross-platform price divergence (same canonical product priced >30% differently), and suspicious patterns (coordinated price changes). Run after each scrape on Kaggle. Output alerts to `data/alerts/price_anomalies.json`. Start with z-score on rolling window, upgrade to isolation forest if needed.

---

## 5. Product Image Similarity

**Priority:** Low | **When:** After image scraping is added
**Quota:** ~15 min/run

> Add visual product matching as a 3rd signal alongside text embeddings + reranker. Scrape product thumbnail images, embed with CLIP-ViT-B/32 on Kaggle GPU, compute visual similarity matrix. Fuse with text similarity (weighted: 0.7 text + 0.3 visual). Particularly useful for products with identical names but different packaging/variants.

---

## 6. Fix Zepto & Instamart Inventory Data (Sales Estimation Broken)

**Priority:** Critical | **When:** Before next sales calculation
**Quota:** N/A (local fix)

> **Problem:** Sales estimation (`morning_inv - night_inv`) produces zero for Zepto and Instamart because neither platform populates `inventory_count`. The fallback `COALESCE(inventory_count, max_cart_qty)` returns a constant 5 for both, so delta is always 0. Only Blinkit has real inventory data (0–50 range, 100% coverage).
>
> **Evidence (2026-03-28):** 9,233 total estimated units — 100% from Blinkit. Zepto (4,955 pairs) and Instamart (670 pairs) both reported 0 units sold.
>
> **Fix options:**
> 1. **Scraper fix**: Find Zepto/Instamart API fields that expose real stock levels (e.g., `available_quantity`, `inventory`, `stock_count`) and map to `inventory_count`
> 2. **Proxy signal**: Use `in_stock` boolean transitions (in_stock=1 morning → in_stock=0 night = "sold out") as a binary sales signal if real counts aren't available
> 3. **Max cart qty changes**: Some platforms reduce max_cart_qty as stock drops — check if this varies between morning/night
>
> **Also:** Blinkit caps `inventory_count` at 50 (7.1% of obs at ceiling). High-velocity SKUs are underestimated. No fix possible without Blinkit exposing higher counts.

---

## 6b. Fix Zepto Scraper Dedup

**Priority:** High | **When:** Before next scrape
**Quota:** N/A (local fix)

> Zepto scraper produces duplicate products (same product appears twice with identical data). This causes oversized clusters in normalization (>3 mappings per canonical). Fix the scraper dedup logic in `src/agents/scraper/` to deduplicate before persisting to DB. Check `platform_product_id` uniqueness.

---

## 7. ~~LLM Judge Cleanup on Flagged Pairs~~ DONE (2026-03-29)

> Ran `python eval/eval_normalization.py --llm-judge --fix`. 126 ambiguous pairs evaluated, 91 bad matches deleted, 35 verified correct. Report: `reports/llm-judge-cleanup.md`.

---

## 8. Incremental Normalization After Scrapes

**Priority:** Medium | **When:** After scraping pipeline is stable
**Quota:** ~5 min per incremental run

> Currently `--normalize` requires pre-cached Kaggle results. Add auto-detection of new unmapped products after scrapes. If unmapped count > threshold, auto-trigger Kaggle embedding run + normalize. Run locally on laptop via cron or manual trigger.

---

## Quota Budget (Estimated Weekly)

| Task | Frequency | GPU Time | Weekly |
|------|-----------|----------|--------|
| BGE-M3 embedding + reranking | 2x/day | 8 min | 1.9 hrs |
| Fine-tuning (monthly) | ~1x/month | 2 hrs | ~0.5 hrs avg |
| LLM validation | on-demand | 10 min | ~0.2 hrs |
| Forecasting | 1x/week | 30 min | 0.5 hrs |
| Anomaly detection | 2x/day | 5 min | 1.2 hrs |
| **Total** | | | **~4.3 hrs/week** |

**Remaining headroom:** ~25.7 hrs/week (86% unused)
