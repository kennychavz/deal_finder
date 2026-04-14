"""LLM-based similarity signal using Gemini 2.0 Flash.

Sends source + candidate product info to Gemini and asks for a structured
infringement probability assessment. This captures nuance that rule-based
signals miss (e.g. "this is clearly a knockoff because it uses the exact
same marketing copy but swaps the brand name").

Uses the free tier: 15 RPM, 1M tokens/day.
"""

from __future__ import annotations

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


class LLMSimilaritySignal(BaseSignal):
    """Use Gemini 2.0 Flash to assess infringement probability.

    Requires GEMINI_API_KEY env var. Falls back gracefully if missing or rate-limited.
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

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    url,
                    params={"key": self._api_key},
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()

            # Extract text from Gemini response
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

        except httpx.HTTPStatusError as e:
            log.warning("Gemini API error %s: %s", e.response.status_code, e.response.text[:200])
            return SignalResult(
                name=self.name,
                score=0.5,
                weight=self.default_weight,
                raw={"error": f"HTTP {e.response.status_code}"},
                reason=f"LLM signal failed — API error {e.response.status_code}",
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
