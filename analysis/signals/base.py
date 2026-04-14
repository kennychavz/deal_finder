"""Base classes for scoring signals."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class SignalResult:
    """Output of a single scoring signal."""

    name: str                       # e.g. "title_similarity"
    score: float                    # 0.0 – 1.0 (1 = strongest match)
    weight: float                   # how much this signal counts in the final score
    raw: dict = field(default_factory=dict)   # debug values (cosine, hash distance, etc.)
    reason: str = ""                # human-readable explanation


class BaseSignal(ABC):
    """Interface every signal must implement."""

    name: str = "base"
    default_weight: float = 1.0

    @abstractmethod
    async def compute(
        self,
        source: dict,
        candidate: dict,
    ) -> SignalResult:
        """Score a candidate against the source product.

        Args:
            source: ProductInfo.to_dict() of the original listing.
            candidate: Scraped result dict from Amazon/eBay scraper.

        Returns:
            SignalResult with score in [0, 1].
        """
        ...
