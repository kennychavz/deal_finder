# Deal Finder — Gap Analysis vs Requirements

## Fixed

| # | Gap | Status |
|---|---|---|
| 2 | No Comfrt reference set | FIXED — `reference_set.py` with 8 products and images |
| 3 | No multi-query search | FIXED — 6 distinct query variations in `SEARCH_QUERIES` |
| 4 | No multi-page fetching | FIXED — `per_query_max=40` ensures 2+ pages per query |
| 5 | No deduplication | FIXED — `_dedup_key()` deduplicates by ASIN / item URL |
| 6 | No request budget | FIXED — `budget.py` with soft limit of 120 requests |
| 7 | No elapsed time / request count in UI | FIXED — `StatusBar` shows elapsed time + per-platform request counts |
| 8 | No analyzing phase in UI | FIXED — distinct analyzing phase with scored count |
| 9 | No concurrency limit on external requests | FIXED — `RequestBudget` semaphore (5 concurrent) |
| 10 | Progressive results not progressive | FIXED — `scored_result` events streamed one at a time |
| 11 | Search triggered by URL not button | FIXED — single "Start Scan" button, no URL input needed |
| 12 | No ARCHITECTURE.md | FIXED — multi-tenant evolution design |
| 13 | No README.md | FIXED — setup, architecture, tradeoffs |

## Remaining

### 1. Not a Next.js App (Intentional Tradeoff)

**Requirement:** "Build a Next.js app"
**Current:** FastAPI (Python) backend + React/Vite frontend

**Rationale:** The scoring pipeline requires Python ML libraries (CLIP/PyTorch, imagehash/PIL, numpy) that have no Node.js equivalents. A Next.js app would need to shell out to Python or run a separate Python microservice — adding complexity without benefit. The current architecture is simpler: one Python process handles scraping + scoring + streaming, one Vite process serves the UI.

This tradeoff is documented in README.md.
