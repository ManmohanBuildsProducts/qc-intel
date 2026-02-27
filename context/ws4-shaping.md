---
shaping: true
---

# WS4: Frontend Dashboard — Shaping

## Source

> Instead of using CLI, I want a frontend to test this. A dashboard to view reports for a brand,
> see data for it, see which categories it's in, its rank compared to others.
> I want to reach the extent where I'm giving queries which are more arbitrary and able to see
> analysis on it — like if Amul in milk wants to enter protein, analyze packaged protein drinks,
> rank them, where is whitespace, in which price range.
> Will start as internal testing tool, then publish on LinkedIn/Twitter to show work with AI.

## Requirements (R)

| ID | Requirement | Status |
|----|-------------|--------|
| R0 | View AI-generated market intelligence report for a brand + category | Core goal |
| R1 | Structured inputs: brand, category, analysis type (dropdowns populated from DB) | Must-have |
| R2 | Report display: markdown text + data tables + Chart.js charts inline | Must-have |
| R3 | Read-only — no pipeline triggers from frontend (CLI stays) | Must-have |
| R4 | FastAPI backend exposing existing Python services as API | Must-have |
| R5 | Next.js + React + Tailwind + Chart.js frontend | Must-have |
| R6 | Demo-quality visual polish, dark mode (LinkedIn/Twitter shareable) | Must-have |
| R7 | Zero paid services — only existing Claude API costs | Constraint |
| R8 | Data explorer: browse products, prices, platform availability from DB | Nice-to-have |

## Selected Shape: A — Monorepo Analytics Dashboard

| Part | Mechanism | Flag |
|------|-----------|:----:|
| **A1** | **FastAPI layer** — thin API wrapping existing Python services (`AnalyticsService`, repositories). Endpoints return chart-ready structured JSON. Lives in `api/` folder. | |
| **A2** | **Report generation endpoint** — `/api/reports/generate` takes brand + category, calls `AnalyticsService.generate_report()`, returns structured report with text sections + chart data | |
| **A3** | **Data endpoints** — `/api/brands`, `/api/categories`, `/api/products`, `/api/prices` — populate dropdowns and data explorer. Chart-ready formats (arrays with labels/values). | |
| **A4** | **Next.js frontend** — `web/` folder. Single-page app with brand/category selector → report view. Dark theme, Tailwind. | |
| **A5** | **Report renderer** — markdown text rendered with `react-markdown`, data tables with styled components, Chart.js charts (price distribution, platform comparison, market share) inline | |
| **A6** | **Loading UX** — skeleton/spinner while Claude generates report (10-30s). No streaming, wait for full response. | |

## Fit Check: R × A

| Req | Requirement | Status | A |
|-----|-------------|--------|:-:|
| R0 | View AI-generated market intelligence report for a brand + category | Core goal | ✅ |
| R1 | Structured inputs: brand, category, analysis type (dropdowns populated from DB) | Must-have | ✅ |
| R2 | Report display: markdown text + data tables + Chart.js charts inline | Must-have | ✅ |
| R3 | Read-only — no pipeline triggers from frontend (CLI stays) | Must-have | ✅ |
| R4 | FastAPI backend exposing existing Python services as API | Must-have | ✅ |
| R5 | Next.js + React + Tailwind + Chart.js frontend | Must-have | ✅ |
| R6 | Demo-quality visual polish, dark mode (LinkedIn/Twitter shareable) | Must-have | ✅ |
| R7 | Zero paid services — only existing Claude API costs | Constraint | ✅ |
| R8 | Data explorer: browse products, prices, platform availability from DB | Nice-to-have | ✅ |

## Scope

**In:**
- FastAPI API layer wrapping existing `AnalyticsService`, repositories
- Next.js frontend with brand/category selection → report view
- Chart.js for price distributions, platform comparisons, market share
- Markdown report rendering with styled tables
- Dark mode, desktop-first

**Out:**
- Pipeline triggers from UI (scrape, normalize, calculate-sales)
- Free-text natural language queries (future)
- User auth, multi-tenancy
- Streaming report generation (wait for full response)
- Mobile optimization (desktop-first for demo videos)

## Decisions

- **Monorepo**: `api/` (FastAPI) + `web/` (Next.js) alongside existing `src/`
- **Dark mode**: locked in as design direction
- **Structured inputs only**: dropdowns for brand/category, not free-text (v1)
- **Chart.js**: free, lightweight, sufficient for demo
- **Desktop-first**: optimized for screen recording demos

## DesignOps Assessment

- **Complexity:** medium — new UI surface, single-page with limited interactions
- Required artifacts: `00_System_Map`, `01_Design_Directive`, `02_Moodboard`
- Moodboard: 10+ refs (analytics dashboards, dark theme data UIs)
- **Gate status:** A (shaping complete, design pending)

## Project Structure (after WS4)

```
qc-intel/
├── src/           ← existing Python pipeline
├── api/           ← new FastAPI layer (thin)
├── web/           ← new Next.js frontend
├── tests/         ← existing Python tests
├── analyze.py     ← existing CLI
├── context/       ← project docs
└── ...
```
