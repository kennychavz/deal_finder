"""Brand fuzzy matching signal."""

from __future__ import annotations

import re

from .base import BaseSignal, SignalResult


def _normalize(text: str) -> str:
    """Lowercase, strip non-alphanumeric, collapse whitespace."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", text.lower())).strip()


def _levenshtein_ratio(a: str, b: str) -> float:
    """Normalized Levenshtein similarity (1 = identical, 0 = totally different)."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0

    n, m = len(a), len(b)
    if n > m:
        a, b = b, a
        n, m = m, n

    prev = list(range(n + 1))
    for j in range(1, m + 1):
        curr = [j] + [0] * n
        for i in range(1, n + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[i] = min(curr[i - 1] + 1, prev[i] + 1, prev[i - 1] + cost)
        prev = curr

    distance = prev[n]
    max_len = max(n, m)
    return 1.0 - (distance / max_len)


class BrandMatchSignal(BaseSignal):
    """Check if the source brand appears in the candidate listing.

    Three checks (best wins):
    1. Exact substring match in candidate title → 1.0
    2. Fuzzy Levenshtein match against candidate title tokens → ratio
    3. Candidate has no recognizable brand mention → 0.0
    """

    name = "brand_match"
    default_weight = 0.20

    async def compute(self, source: dict, candidate: dict) -> SignalResult:
        brand_raw = source.get("brand", "")
        brand = _normalize(brand_raw)

        if not brand:
            return SignalResult(
                name=self.name,
                score=0.5,   # neutral — can't score without a brand
                weight=self.default_weight,
                raw={"source_brand": brand_raw, "note": "no brand in source"},
                reason="Source has no brand — signal neutral",
            )

        cand_title = _normalize(candidate.get("title") or "")
        cand_seller = _normalize(candidate.get("seller") or "")

        # --- 1. Exact substring ---
        if brand in cand_title or brand in cand_seller:
            return SignalResult(
                name=self.name,
                score=1.0,
                weight=self.default_weight,
                raw={
                    "source_brand": brand_raw,
                    "match_type": "exact_substring",
                    "found_in": "title" if brand in cand_title else "seller",
                },
                reason=f"Brand '{brand_raw}' found verbatim in candidate",
            )

        # --- 2. Fuzzy match against candidate title tokens ---
        cand_tokens = cand_title.split()
        brand_tokens = brand.split()

        # Try matching brand as n-gram window in candidate title
        best_ratio = 0.0
        best_match = ""
        n = len(brand_tokens)
        for i in range(len(cand_tokens) - n + 1):
            window = " ".join(cand_tokens[i : i + n])
            ratio = _levenshtein_ratio(brand, window)
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = window

        # Also try single-token match if brand is one word
        if len(brand_tokens) == 1:
            for token in cand_tokens:
                ratio = _levenshtein_ratio(brand, token)
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_match = token

        score = best_ratio if best_ratio >= 0.6 else 0.0

        if score >= 0.85:
            reason = f"Brand '{brand_raw}' fuzzy-matched to '{best_match}' ({best_ratio:.0%})"
        elif score >= 0.6:
            reason = f"Possible brand match: '{best_match}' ({best_ratio:.0%} similar to '{brand_raw}')"
        else:
            reason = f"Brand '{brand_raw}' not found in candidate title"

        return SignalResult(
            name=self.name,
            score=round(score, 4),
            weight=self.default_weight,
            raw={
                "source_brand": brand_raw,
                "best_match": best_match,
                "levenshtein_ratio": round(best_ratio, 4),
                "match_type": "fuzzy",
                "candidate_title": candidate.get("title", ""),
            },
            reason=reason,
        )
