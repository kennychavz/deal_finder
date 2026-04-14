"""Global request budget tracker and concurrency limiter.

Provides a shared semaphore for external HTTP requests and a soft
request budget that scrapers check before making new requests.
"""

from __future__ import annotations

import asyncio
import time
import logging

log = logging.getLogger(__name__)


class RequestBudget:
    """Track request counts and enforce soft budget + concurrency limits."""

    def __init__(self, soft_limit: int = 120, concurrency: int = 5):
        self.soft_limit = soft_limit
        self.concurrency = concurrency
        self._semaphore = asyncio.Semaphore(concurrency)
        self._lock = asyncio.Lock()
        self._counts: dict[str, int] = {}  # platform -> count
        self._total = 0
        self._start_time = time.monotonic()

    @property
    def total(self) -> int:
        return self._total

    @property
    def remaining(self) -> int:
        return max(0, self.soft_limit - self._total)

    @property
    def exhausted(self) -> bool:
        return self._total >= self.soft_limit

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self._start_time

    def counts_by_platform(self) -> dict[str, int]:
        return dict(self._counts)

    async def acquire(self, platform: str, cost: int = 1) -> bool:
        """Try to acquire request slot(s). Returns False if budget exhausted.

        Args:
            platform: Platform name for tracking (e.g. "amazon", "ebay").
            cost: Number of requests this operation will make (e.g. page count).
        """
        if self.exhausted:
            log.info("Request budget exhausted (%d/%d)", self._total, self.soft_limit)
            return False
        await self._semaphore.acquire()
        async with self._lock:
            self._total += cost
            self._counts[platform] = self._counts.get(platform, 0) + cost
        return True

    def release(self) -> None:
        """Release the concurrency semaphore slot."""
        self._semaphore.release()

    def summary(self) -> dict:
        return {
            "total_requests": self._total,
            "soft_limit": self.soft_limit,
            "remaining": self.remaining,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "by_platform": dict(self._counts),
        }
