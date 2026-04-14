"""LLM-based similarity signal using Gemini 2.0 Flash.

Sends source + candidate product info to Gemini and asks for a structured
infringement probability assessment. This captures nuance that rule-based
signals miss (e.g. "this is clearly a knockoff because it uses the exact
same marketing copy but swaps the brand name").

Uses the free tier: 15 RPM, 1M tokens/day.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

import httpx

from .base import BaseSignal, SignalResult

log = logging.getLogger(__name__)

_GEMINI_MODEL = "gemini-2.0-flash"
_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

_SYSTEM_PROMPT = """You are a product infringement analyst. Given a SOURCE product listing and a CANDIDATE listing found on a marketplace, assess the probability that the candidate is selling the same product or an infringing copy.

Respond ONLY with valid JSON (no markdown, no code fences):
{
  "score": <float 0.0-1.0>,
  "confidence": <float 0.0-1.0>,
  "reasoning": "<1-2 sentence explanation>",
  "signals": {
    "same_product": <bool>,
    "possible_counterfeit": <bool>,
    "brand_misuse": <bool>,
    "copied_description": <bool>
  }
}

Score meaning:
- 0.9-1.0: Almost certainly the same product or direct counterfeit
- 0.7-0.9: Very likely related/infringing
- 0.4-0.7: Possibly related but uncertain
- 0.0-0.4: Probably different product"""


def _build_prompt(source: dict, candidate: dict) -> str:
    # Only send relevant fields to keep tokens low
    src_fields = {
        k: source.get(k, "")
        for k in ["title", "brand", "price", "currency", "product_type",
                   "material", "color", "description"]
        if source.get(k)
    }
    cand_fields = {
        k: candidate.get(k, "")
        for k in ["title", "price", "currency", "seller", "condition",
                   "marketplace", "rating", "review_count"]
        if candidate.get(k) is not None
    }

    return f"""SOURCE PRODUCT:
{json.dumps(src_fields, indent=2)}

CANDIDATE LISTING:
{json.dumps(cand_fields, indent=2)}

Assess infringement probability."""


_LLM_SEMAPHORE = asyncio.Semaphore(2)  # max 2 concurrent LLM calls


class LLMSimilaritySignal(BaseSignal):
    """Use Gemini 2.0 Flash to assess infringement probability.

    Requires GEMINI_API_KEY env var. Falls back gracefully if missing or rate-limited.
    Rate limited to 2 concurrent requests to avoid 429s on free tier.
    """

    name = "llm_assessment"
    default_weight = 0.10

    def __init__(self, api_key: str | None = None, timeout: float = 15.0):
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self._timeout = timeout

    async def compute(self, source: dict, candidate: dict) -> SignalResult:
        if not self._api_key:
            return SignalResult(
                name=self.name,
                score=0.5,  # neutral
                weight=self.default_weight,
                raw={"note": "GEMINI_API_KEY not set"},
                reason="LLM signal skipped — no API key",
            )

        await _LLM_SEMAPHORE.acquire()
        try:
            return await self._call_llm(source, candidate)
        finally:
            _LLM_SEMAPHORE.release()
            await asyncio.sleep(0.5)  # space out requests to avoid 429

    async def _call_llm(self, source: dict, candidate: dict) -> SignalResult:
        prompt = _build_prompt(source, candidate)
        url = _GEMINI_URL.format(model=_GEMINI_MODEL)

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": _SYSTEM_PROMPT + "\n\n" + prompt}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 256,
                "responseMimeType": "application/json",
            },
        }

        # Retry up to 3 times on 429 (rate limit) with increasing backoff
        data = None
        last_status = 0
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(
                        url,
                        params={"key": self._api_key},
                        json=payload,
                    )
                    last_status = resp.status_code
                    if resp.status_code == 429:
                        wait = 2 ** attempt * 2  # 2s, 4s, 8s
                        log.debug("Gemini 429, retrying in %ds (attempt %d)", wait, attempt + 1)
                        await asyncio.sleep(wait)
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    break
            except httpx.HTTPStatusError:
                if last_status == 429:
                    continue
                raise

        if data is None:
            return SignalResult(
                name=self.name,
                score=0.5,
                weight=self.default_weight,
                raw={"error": f"Rate limited after 3 retries (HTTP {last_status})"},
                reason="LLM signal failed, rate limited after retries",
            )

        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            result = json.loads(text)

            score = float(result.get("score", 0.5))
            score = max(0.0, min(1.0, score))
            reasoning = result.get("reasoning", "No reasoning provided")
            confidence = result.get("confidence", 0.5)
            signals = result.get("signals", {})

            return SignalResult(
                name=self.name,
                score=round(score, 4),
                weight=self.default_weight,
                raw={
                    "llm_score": score,
                    "confidence": confidence,
                    "llm_reasoning": reasoning,
                    "llm_signals": signals,
                    "model": _GEMINI_MODEL,
                },
                reason=reasoning,
            )
        except Exception as e:
            log.warning("Gemini signal failed: %s", e)
            return SignalResult(
                name=self.name,
                score=0.5,
                weight=self.default_weight,
                raw={"error": str(e)},
                reason="LLM signal failed — falling back to neutral",
            )
