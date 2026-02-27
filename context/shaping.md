---
shaping: true
---

# QC Intel — Shaping

## Source

> Build a POC similar to GobbleCube.ai. Multi-agent pipeline using Claude Agent SDK:
> scraping, sales estimation, normalization, analytics across quick commerce platforms.
> Scope: Blinkit + Zepto + Instamart, all Gurugram pincodes.
> Hackathon: 10 hours. Deep on 3 platforms rather than shallow on 7.
> Demo: `python analyze.py --brand "Amul"` → category report.

## Requirements (R)

| ID | Requirement | Status |
|----|-------------|--------|
| R0 | Working QC data intelligence pipeline, end-to-end | Core goal |
| R1 | Demo = CLI script with brand name → category report | Core goal |
| R2 | Three platforms: Blinkit, Zepto, Swiggy Instamart | Must-have |
| R3 | Normalize same product across platforms into one entity | Must-have |
| R4 | Estimate sales volume via add-to-cart inventory delta | Must-have |
| R5 | Track prices and availability daily (time-series capable) | Must-have |
| R6 | Answer category questions — white space, competitive landscape, pricing tiers | Must-have |
| R7 | Built entirely with Claude Agent SDK (custom agents) | Must-have |
| R8 | Scoped to Gurugram, all pincodes | Must-have |
| R9 | Buildable in ~24 hours, hackathon pace | Constraint |

## Selected Shape: A — Multi-Agent QC Intelligence Pipeline

| Part | Mechanism | Flag |
|------|-----------|:----:|
| **A1** | **Scraper agent** — Claude Agent SDK agent with Playwright MCP. Uses Claude to parse varying page structures dynamically (no hardcoded selectors). Scrapes product data (name, price, images, description, category) for Blinkit, Zepto, Instamart across Gurugram pincodes | ⚠️ |
| **A2** | **Sales estimator agent** — Claude Agent SDK agent with Playwright MCP. Simulates add-to-cart at 2 daily checkpoints per product/pincode. Stores max-qty snapshots, computes delta = sales proxy | ⚠️ |
| **A3** | **Normalization agent** — Claude Agent SDK agent. Generates product embeddings via Claude, clusters/maps same product across platforms into canonical entities | ⚠️ |
| **A4** | **Daily logger** — SQLite time-series store. Schema: canonical_product_id, platform, pincode, price, availability, max_cart_qty, estimated_sales, timestamp | |
| **A5** | **Analytics agent** — Claude Agent SDK agent with Read + Bash. Takes brand name + category, queries normalized data, generates competitive analysis report | ⚠️ |
| **A6** | **Orchestrator** — Python script using Agent SDK to coordinate pipeline: scrape → estimate → normalize → log → analyze | |

## Fit Check: R × A

| Req | Requirement | Status | A |
|-----|-------------|--------|:-:|
| R0 | Working pipeline end-to-end | Core goal | ✅ |
| R1 | CLI demo: brand → report | Core goal | ✅ |
| R2 | Blinkit + Zepto + Instamart | Must-have | ✅ |
| R3 | Cross-platform normalization | Must-have | ✅ |
| R4 | Sales volume estimation | Must-have | ❌ |
| R5 | Daily price/availability tracking | Must-have | ✅ |
| R6 | Category-level analytics | Must-have | ✅ |
| R7 | Claude Agent SDK agents | Must-have | ✅ |
| R8 | Gurugram pincodes | Must-have | ✅ |
| R9 | 24 hours | Constraint | ✅ |

**Notes:**
- R4 fails: A2 mechanism (add-to-cart simulation) is ⚠️ — anti-bot risk per platform unresolved
- R9: 24-hour timeline gives room for full pipeline implementation

## Decisions

- **Depth over breadth**: 3 platforms, all Gurugram pincodes
- **Agent SDK only**: all agents built with `claude-agent-sdk`
- **Phase 1 demo**: CLI script, not a dashboard
- **Risk accepted**: A2 (sales estimation) is high-risk, will attempt anyway
- **Timeline extended**: 24 hours (was 10), full pipeline now feasible
- **Competitor ref**: GobbleCube.ai research in `~/Projects/MyNotes/99_Inbox/gobblecube-research.md`
