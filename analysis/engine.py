"""Scoring engine — orchestrates signals and produces explainable scores.

Public API:
    from analysis import analyze

    results = await analyze(source_product_dict, candidate_list)
    # returns list[dict] in same order as candidates
"""

from __future__ import annotations

import asyncio
import logging

from .signals import (
    BaseSignal,
    SignalResult,
    TitleSimilaritySignal,
    BrandMatchSignal,
    ImageHashSignal,
    PriceAnomalySignal,
    CLIPSimilaritySignal,
    LLMSimilaritySignal,
)

log = logging.getLogger(__name__)


def _build_output(candidate: dict, signals: list[SignalResult]) -> dict:
    """Build the output dict for one candidate matching the I/O spec exactly.

    Output shape:
        {
            "url": "...",
            "overall_score": 0.82,
            "reasoning": "...",
            "signals": {
                "title_similarity": { "score", "weight", "reason", "raw" },
                ...
            }
        }
    """
    # Weighted average
    total_weight = sum(s.weight for s in signals)
    if total_weight == 0:
        overall = 0.0
    else:
        overall = sum(s.score * s.weight for s in signals) / total_weight

    # Build signals dict
    signals_dict = {}
    for s in signals:
        signals_dict[s.name] = {
            "score": round(s.score, 4),
            "weight": round(s.weight, 4),
            "reason": s.reason,
            "raw": s.raw,
        }

    # Top reasoning: pick top 3 signals by contribution, join their reasons
    ranked = sorted(signals, key=lambda s: s.score * s.weight, reverse=True)
    top_reasons = [s.reason for s in ranked[:3] if s.reason]
    reasoning = " | ".join(top_reasons)

    return {
        "url": candidate.get("url", ""),
        "overall_score": round(overall, 4),
        "reasoning": reasoning,
        "signals": signals_dict,
    }


class ScoringEngine:
    """Run all signals against candidates and produce scored output.

    Usage:
        engine = ScoringEngine()
        results = await engine.score_all(source, candidates)
        # results is list[dict] in same order as input candidates
    """

    def __init__(self, signals: list[BaseSignal] | None = None):
        if signals is None:
            signals = [
                TitleSimilaritySignal(),     # 0.30
                BrandMatchSignal(),          # 0.20
                ImageHashSignal(),           # 0.15
                PriceAnomalySignal(),        # 0.15
                CLIPSimilaritySignal(),      # 0.10
                LLMSimilaritySignal(),       # 0.10
            ]
        self.signals = signals

    async def score_one(self, source: dict, candidate: dict) -> dict:
        """Score a single candidate. Returns the output dict."""
        results: list[SignalResult] = await asyncio.gather(
            *(sig.compute(source, candidate) for sig in self.signals)
        )
        return _build_output(candidate, results)

    async def score_all(
        self,
        source: dict,
        candidates: list[dict],
        concurrency: int = 10,
    ) -> list[dict]:
        """Score all candidates against the source product.

        Args:
            source: ProductInfo dict (from product_extractor.to_dict()).
            candidates: List of scraped result dicts from Amazon/eBay.
            concurrency: Max parallel scoring tasks.

        Returns:
            list[dict] in the SAME ORDER as input candidates.
            Each dict has: url, overall_score, reasoning, signals.
        """
        sem = asyncio.Semaphore(concurrency)

        async def _bounded(idx: int, cand: dict) -> tuple[int, dict]:
            async with sem:
                result = await self.score_one(source, cand)
                return idx, result

        tasks = [_bounded(i, c) for i, c in enumerate(candidates)]
        completed = await asyncio.gather(*tasks)

        # Restore original order
        ordered = [None] * len(candidates)
        for idx, result in completed:
            ordered[idx] = result

        return ordered


async def analyze(
    source: dict,
    candidates: list[dict],
    concurrency: int = 10,
) -> list[dict]:
    """Top-level entry point for the analysis package.

    Args:
        source: ProductInfo dict with title, brand, price, images, etc.
        candidates: List of scraped result dicts with title, price, image_url, etc.
        concurrency: Max parallel scoring tasks.

    Returns:
        list[dict] — one entry per candidate, same order as input.
        Each entry:
        {
            "url": "https://...",
            "overall_score": 0.82,
            "reasoning": "Strong title match | Brand found | ...",
            "signals": {
                "title_similarity": {"score": 0.85, "weight": 0.3, "reason": "...", "raw": {...}},
                "brand_match":      {"score": 0.0,  "weight": 0.2, "reason": "...", "raw": {...}},
                ...
            }
        }
    """
    engine = ScoringEngine()
    return await engine.score_all(source, candidates, concurrency=concurrency)
