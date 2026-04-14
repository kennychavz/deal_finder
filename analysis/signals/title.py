"""Title similarity signal using TF-IDF cosine similarity + token overlap."""

from __future__ import annotations

import re
import math
from collections import Counter

from .base import BaseSignal, SignalResult


def _tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, split into tokens."""
    return re.findall(r"[a-z0-9]+", text.lower())


def _cosine_similarity(a: Counter, b: Counter) -> float:
    """Cosine similarity between two term-frequency vectors."""
    common = set(a) & set(b)
    if not common:
        return 0.0
    dot = sum(a[k] * b[k] for k in common)
    mag_a = math.sqrt(sum(v * v for v in a.values()))
    mag_b = math.sqrt(sum(v * v for v in b.values()))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _jaccard(a: set, b: set) -> float:
    """Jaccard index (intersection / union)."""
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


# Tokens that add noise — common marketplace filler
_STOPWORDS = frozenset({
    "for", "with", "the", "and", "a", "an", "in", "on", "of", "to",
    "new", "free", "shipping", "fast", "sale", "hot", "best", "top",
    "buy", "deal", "lot", "set", "pack", "pcs", "us", "usa",
})


class TitleSimilaritySignal(BaseSignal):
    """Compare source title vs candidate title.

    Combines cosine similarity (captures overall overlap) with
    Jaccard index (captures exact token match ratio).
    """

    name = "title_similarity"
    default_weight = 0.30

    def __init__(self, cosine_weight: float = 0.6, jaccard_weight: float = 0.4):
        self._cw = cosine_weight
        self._jw = jaccard_weight

    async def compute(self, source: dict, candidate: dict) -> SignalResult:
        src_title = source.get("title", "")
        cand_title = candidate.get("title", "")
        brand = source.get("brand", "")

        src_tokens = _tokenize(src_title)
        cand_tokens = _tokenize(cand_title)

        # Filter stopwords for scoring (keep originals for debug)
        src_filtered = [t for t in src_tokens if t not in _STOPWORDS]
        cand_filtered = [t for t in cand_tokens if t not in _STOPWORDS]

        src_counts = Counter(src_filtered)
        cand_counts = Counter(cand_filtered)

        cosine = _cosine_similarity(src_counts, cand_counts)
        jaccard = _jaccard(set(src_filtered), set(cand_filtered))

        score = self._cw * cosine + self._jw * jaccard

        # Brand name in candidate title is a strong infringement signal.
        # If the candidate literally says "Comfrt" in the title, boost the score
        # significantly since legitimate competitors would not use this brand name.
        brand_in_title = False
        if brand and brand.lower() in cand_title.lower():
            brand_in_title = True
            score = max(score, 0.85)

        # Shared and missing tokens for explainability
        shared = set(src_filtered) & set(cand_filtered)
        missing = set(src_filtered) - set(cand_filtered)
        extra = set(cand_filtered) - set(src_filtered)

        if brand_in_title:
            reason = f"Brand name '{brand}' found in title, strong infringement signal"
        elif score >= 0.7:
            reason = f"Strong title match, shared: {', '.join(sorted(shared)[:6])}"
        elif score >= 0.4:
            reason = f"Partial title match, missing: {', '.join(sorted(missing)[:4])}"
        else:
            reason = f"Weak title match, only {len(shared)}/{len(set(src_filtered))} tokens overlap"

        return SignalResult(
            name=self.name,
            score=round(score, 4),
            weight=self.default_weight,
            raw={
                "cosine": round(cosine, 4),
                "jaccard": round(jaccard, 4),
                "brand_in_title": brand_in_title,
                "shared_tokens": sorted(shared),
                "missing_from_candidate": sorted(missing),
                "extra_in_candidate": sorted(extra),
                "source_title": src_title,
                "candidate_title": cand_title,
            },
            reason=reason,
        )
