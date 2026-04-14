"""FastAPI backend — Comfrt infringement detection pipeline.

Run:
    cd deal_finder
    uvicorn api:app --reload --port 8000

Endpoints:
    POST /api/search     { "max_results": 50 }  → SSE stream
    GET  /api/health     → { "status": "ok" }

SSE events emitted in order:
    source          {reference brand info}
    phase           {"phase": "searching"}
    query_start     {"query": "comfrt hoodie", "index": 0, "total": 6}
    result          {scraped result dict}          (one per result as they arrive)
    lane_done       {"marketplace": "amazon", "query": "...", "count": 5}
    lane_error      {"marketplace": "ebay", "query": "...", "message": "..."}
    stats           {"elapsed_seconds": 45.2, "total_requests": 12, ...}
    phase           {"phase": "analyzing"}
    scored_result   {single scored result}         (progressive, one at a time)
    phase           {"phase": "done", "summary": {...}}
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import traceback

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from scrapers.amazon_scraper import search_amazon
from scrapers.ebay_scraper import search_ebay
from analysis import analyze
from reference_set import SEARCH_QUERIES, get_reference_source
from budget import RequestBudget

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = FastAPI(title="Deal Finder API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class SearchRequest(BaseModel):
    max_results: int = 50


class _SafeEncoder(json.JSONEncoder):
    """Handle numpy types and other non-standard JSON values."""
    def default(self, obj):
        try:
            import numpy as np
            if isinstance(obj, (np.integer,)):
                return int(obj)
            if isinstance(obj, (np.floating,)):
                return float(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
        except ImportError:
            pass
        return super().default(obj)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, cls=_SafeEncoder)}\n\n"


def _dedup_key(item: dict) -> str | None:
    """Return a dedup key for a scraped result, or None if not dedup-able."""
    # Amazon: always use ASIN if present
    asin = item.get("asin")
    if asin:
        return f"amazon:{asin}"
    # Amazon sponsored URLs contain the real ASIN in the path
    url = item.get("url", "")
    if "amazon.com" in url:
        import re
        m = re.search(r'/dp/([A-Z0-9]{10})', url)
        if m:
            return f"amazon:{m.group(1)}"
        return f"amazon:{url}"
    if "ebay.com" in url:
        # Extract item number from eBay URL
        import re
        m = re.search(r'/itm/(\d+)', url)
        if m:
            return f"ebay:{m.group(1)}"
        return f"ebay:{url}"
    return None


async def _search_one_query(
    query: str,
    marketplace: str,
    max_results: int,
    budget: RequestBudget,
) -> list[dict]:
    """Run a single search query against one marketplace."""
    if budget.exhausted:
        return []

    # Estimate pages: Amazon pages are ~20 items, eBay ~60 items
    if marketplace == "amazon":
        est_pages = max(1, (max_results // 20) + 1)
    else:
        est_pages = max(1, (max_results // 60) + 1)

    if not await budget.acquire(marketplace, cost=est_pages):
        return []

    try:
        if marketplace == "amazon":
            return await search_amazon(query, max_results=max_results)
        else:
            return await search_ebay(query, max_results=max_results)
    except Exception as e:
        log.warning("%s search failed for query '%s': %s", marketplace, query, e)
        return []
    finally:
        budget.release()


async def _search_stream(max_results: int):
    start_time = time.monotonic()
    budget = RequestBudget(soft_limit=120, concurrency=5)

    # ── Send reference source info ──
    source = get_reference_source()
    yield _sse("source", source)
    yield _sse("phase", {"phase": "searching"})

    # ── Phase 1: Multi-query search across both marketplaces ──
    seen_keys: set[str] = set()
    all_candidates: list[dict] = []

    # Fetch enough per query for 2+ pages, but cap per-query to avoid overshoot
    per_query_max = max(20, min(40, max_results // len(SEARCH_QUERIES) + 10))

    for qi, query in enumerate(SEARCH_QUERIES):
        if budget.exhausted:
            log.info("Budget exhausted, stopping at query %d/%d", qi, len(SEARCH_QUERIES))
            break
        if len(all_candidates) >= max_results:
            log.info("Hit max_results=%d, stopping at query %d/%d", max_results, qi, len(SEARCH_QUERIES))
            break

        yield _sse("query_start", {
            "query": query,
            "index": qi,
            "total": len(SEARCH_QUERIES),
        })

        amazon_task = asyncio.create_task(
            _search_one_query(query, "amazon", per_query_max, budget)
        )
        ebay_task = asyncio.create_task(
            _search_one_query(query, "ebay", per_query_max, budget)
        )

        for task, marketplace in [(amazon_task, "amazon"), (ebay_task, "ebay")]:
            try:
                results = await task
                new_count = 0
                for r in results:
                    if len(all_candidates) >= max_results:
                        break

                    r["marketplace"] = marketplace
                    r["source_query"] = query

                    # Deduplicate by ASIN / item URL
                    key = _dedup_key(r)
                    if key and key in seen_keys:
                        continue
                    if key:
                        seen_keys.add(key)

                    all_candidates.append(r)
                    new_count += 1
                    yield _sse("result", r)

                yield _sse("lane_done", {
                    "marketplace": marketplace,
                    "query": query,
                    "count": new_count,
                    "total_so_far": len(all_candidates),
                })
            except Exception as e:
                log.error("%s scrape failed for '%s': %s\n%s",
                          marketplace, query, e, traceback.format_exc())
                yield _sse("lane_error", {
                    "marketplace": marketplace,
                    "query": query,
                    "message": str(e),
                })

        # Emit stats after each query pair
        yield _sse("stats", {
            "elapsed_seconds": round(time.monotonic() - start_time, 1),
            **budget.summary(),
        })

    # ── Phase 2: Score all candidates (progressive) ──
    yield _sse("phase", {"phase": "analyzing"})

    if all_candidates:
        try:
            scored = await analyze(source, all_candidates)

            # Merge and sort by score desc, then stream one at a time
            merged = []
            for candidate, analysis_result in zip(all_candidates, scored):
                merged.append({
                    **candidate,
                    "similarity_score": analysis_result["overall_score"],
                    "score_breakdown": {
                        "overall": analysis_result["overall_score"],
                        "reasoning": analysis_result["reasoning"],
                        **analysis_result["signals"],
                    },
                })

            merged.sort(key=lambda x: x.get("similarity_score", 0), reverse=True)
            for item in merged:
                yield _sse("scored_result", item)

        except Exception as e:
            log.error("Scoring failed: %s\n%s", e, traceback.format_exc())
            yield _sse("error", {"message": f"Scoring failed: {e}"})

    # ── Done ──
    elapsed = round(time.monotonic() - start_time, 1)
    yield _sse("phase", {
        "phase": "done",
        "summary": {
            "elapsed_seconds": elapsed,
            "total_candidates": len(all_candidates),
            "deduped_count": len(seen_keys),
            **budget.summary(),
        },
    })


@app.post("/api/search")
async def search(req: SearchRequest):
    return StreamingResponse(
        _search_stream(req.max_results),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/health")
async def health():
    return {"status": "ok"}
