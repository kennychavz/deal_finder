# Deal Finder — Comfrt Infringement Detector

Detects potential counterfeit [Comfrt](https://comfrt.com/) product listings on Amazon and eBay. A single "Start Scan" button triggers 6 search queries across both marketplaces, deduplicates by ASIN/item ID, and scores each candidate against a reference set of 8 authentic Comfrt products using 6 independent signals. Results stream progressively with explainable probability scores.

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- (Optional) `GEMINI_API_KEY` env var for LLM scoring signal

### Setup

```bash
cd deal_finder

# Python backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# Frontend
cd ui
npm install
cd ..
```

### Run

```bash
# Terminal 1 — Backend (port 8000)
uvicorn api:app --reload --port 8000

# Terminal 2 — Frontend (port 3333, proxies /api to backend)
cd ui && npm run dev
```

Open http://localhost:3333 and click **Start Scan**.

## How It Works

### Pipeline

1. **Search** — Runs 6 query variations ("comfrt blanket hoodie", "comfrt sweatshirt", "comfrt cloud hoodie", etc.) against both Amazon and eBay via ScraperAPI. Fetches 2+ pages per query within a soft budget of ~120 requests. Concurrency is limited to 5 simultaneous external requests.
2. **Deduplicate** — Removes duplicate listings by ASIN (Amazon) or item URL (eBay) across all queries.
3. **Score** — Each candidate is scored against a reference set of 8 authentic Comfrt products using 6 signals:

| Signal | Weight | Method |
|---|---|---|
| Title Similarity | 0.30 | TF-IDF cosine + Jaccard index |
| Brand Match | 0.20 | Fuzzy Levenshtein matching |
| Image Similarity | 0.15 | Perceptual hashing (pHash + dHash) |
| Price Anomaly | 0.15 | Counterfeit likelihood based on price ratio |
| CLIP Similarity | 0.10 | ViT-B-32 vision embedding cosine similarity |
| LLM Assessment | 0.10 | Gemini 2.0 Flash evaluation |

4. **Stream** — Results stream to the frontend via SSE as they are scored, sorted by score descending. High-confidence candidates surface first.

### Job Orchestration

- **Concurrency limit**: 5 simultaneous external HTTP requests via asyncio semaphore
- **Soft request budget**: ~120 total requests; gracefully stops fetching when exhausted
- **UI observability**: Total elapsed time and request count broken down by platform displayed in real-time
- **Multi-query**: 6 distinct search variations to maximize coverage
- **Deduplication**: By ASIN (Amazon) and item URL (eBay) to prevent duplicates across queries

### Scoring Explainability

Each result displays:
- Final probability score (0–1)
- Top contributing reasons (human-readable)
- Per-signal breakdown bars with individual scores, weights, and reasons
- Raw signal values for debugging (expandable)

### Graceful Degradation

- Image fetch fails → score using text signals only (image/CLIP signals return 0.0 with reason)
- LLM API unavailable → neutral 0.5 score for that signal
- Scraper fails → falls back to Playwright headless browser
- Request budget exhausted → returns and scores results collected so far

## Architecture

- **Backend**: FastAPI with SSE streaming, asyncio concurrency control
- **Frontend**: React 19 + Vite + Tailwind CSS
- **Scraping**: ScraperAPI (structured endpoints) with Playwright fallback
- **Reference Set**: 8 authentic Comfrt products hardcoded in `reference_set.py`
- **ML Models**: CLIP ViT-B-32 (loaded once, cached), imagehash for perceptual hashing
- **LLM**: Gemini 2.0 Flash via REST API
- **Budget**: Global request counter with per-platform breakdown (`budget.py`)

See [ARCHITECTURE.md](ARCHITECTURE.md) for multi-tenant evolution design.

## Project Structure

```
deal_finder/
├── api.py                      # FastAPI server, SSE streaming, job orchestration
├── reference_set.py            # 8 authentic Comfrt products + 6 search queries
├── budget.py                   # Request budget tracker + concurrency limiter
├── analysis/
│   ├── engine.py               # ScoringEngine orchestration
│   └── signals/
│       ├── title.py            # TF-IDF + Jaccard
│       ├── brand.py            # Fuzzy Levenshtein
│       ├── image.py            # pHash + dHash
│       ├── price.py            # Price ratio anomaly
│       ├── clip.py             # CLIP vision embeddings
│       └── llm.py              # Gemini 2.0 Flash
├── scrapers/
│   ├── product_extractor.py    # Multi-strategy product extraction
│   ├── amazon_scraper.py       # Amazon search (ScraperAPI + Playwright)
│   └── ebay_scraper.py         # eBay search (ScraperAPI + Playwright)
├── ui/                         # React frontend
│   └── src/
│       ├── App.tsx             # Main app, SSE handler, scan button
│       └── components/         # StatusBar, ResultCard, FilterBar, etc.
├── ARCHITECTURE.md             # Multi-tenant evolution design
└── README.md                   # This file
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | No | Enables LLM scoring signal. Without it, LLM signal defaults to neutral 0.5 |

The ScraperAPI key is configured in the scraper modules.

## Tradeoffs & Design Decisions

- **FastAPI + React instead of Next.js**: Chose a Python backend for direct access to ML models (CLIP, imagehash) and the Gemini API without Node.js interop overhead. The scoring signals require numpy, torch, and PIL — native Python libraries. Server Actions would require calling out to a Python microservice anyway.
- **Reference set hardcoded vs scraped**: Hardcoded for reliability. Scraping comfrt.com on every run adds latency and a failure point. Product catalog changes rarely.
- **Scoring batch then stream**: All candidates scored in parallel (asyncio.gather with semaphore), then streamed sorted by score. True per-result streaming would require streaming before sort, losing the "best first" property.
- **Price signal weights**: Suspiciously cheap items score high because counterfeits are typically priced well below authentic retail. This is a deliberate bias toward recall over precision.
