"""Price anomaly signal — counterfeits are often suspiciously cheap."""

from __future__ import annotations

from .base import BaseSignal, SignalResult


class PriceAnomalySignal(BaseSignal):
    """Score based on how the candidate's price compares to the source.

    Logic:
    - Identical price → high score (likely same product)
    - Slightly cheaper (10-30% off) → moderate (could be sale/used)
    - Very cheap (>50% off) → high score (suspicious — possible counterfeit)
    - More expensive → lower score (probably different/premium variant)

    The score represents "how likely is this an infringement" not "how good a deal":
    - Suspiciously cheap branded goods = high infringement probability
    - Same price = likely same/authorized product (moderate)
    - Higher price = less likely counterfeit
    """

    name = "price_anomaly"
    default_weight = 0.15

    def __init__(self, suspicious_threshold: float = 0.50, identical_band: float = 0.10):
        self._suspicious = suspicious_threshold   # >50% cheaper is suspicious
        self._identical_band = identical_band      # within 10% = "same price"

    async def compute(self, source: dict, candidate: dict) -> SignalResult:
        src_price = source.get("price")
        cand_price = candidate.get("price")

        if src_price is None or cand_price is None or src_price <= 0:
            return SignalResult(
                name=self.name,
                score=0.5,   # neutral
                weight=self.default_weight,
                raw={"source_price": src_price, "candidate_price": cand_price},
                reason="Price comparison unavailable — signal neutral",
            )

        ratio = cand_price / src_price
        discount_pct = (1 - ratio) * 100

        # Score mapping:
        # ratio < 0.3  → very suspicious (score ~0.95)
        # ratio 0.3-0.5 → suspicious (score ~0.8)
        # ratio 0.5-0.9 → moderate (score ~0.5-0.7)
        # ratio 0.9-1.1 → same price (score ~0.6)
        # ratio > 1.1  → more expensive (score ~0.3)
        # ratio > 2.0  → much more expensive (score ~0.1)

        if ratio <= 0.3:
            score = 0.95
            reason = f"Extremely cheap ({discount_pct:.0f}% below source) — highly suspicious"
        elif ratio <= 0.5:
            score = 0.80
            reason = f"Very cheap ({discount_pct:.0f}% below source) — suspicious"
        elif ratio <= 0.7:
            score = 0.65
            reason = f"Significantly cheaper ({discount_pct:.0f}% below source)"
        elif ratio <= (1 - self._identical_band):
            score = 0.55
            reason = f"Somewhat cheaper ({discount_pct:.0f}% below source)"
        elif ratio <= (1 + self._identical_band):
            score = 0.60
            reason = f"Similar price (within {self._identical_band*100:.0f}% of source)"
        elif ratio <= 1.5:
            score = 0.35
            reason = f"More expensive ({-discount_pct:.0f}% above source)"
        elif ratio <= 2.0:
            score = 0.20
            reason = f"Much more expensive ({-discount_pct:.0f}% above source)"
        else:
            score = 0.10
            reason = f"Extremely expensive ({ratio:.1f}x source price) — likely different product"

        return SignalResult(
            name=self.name,
            score=round(score, 4),
            weight=self.default_weight,
            raw={
                "source_price": src_price,
                "candidate_price": cand_price,
                "ratio": round(ratio, 4),
                "discount_pct": round(discount_pct, 2),
            },
            reason=reason,
        )
