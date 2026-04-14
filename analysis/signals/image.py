"""Image perceptual hashing signal (pHash + dHash).

Compares candidate image against ALL source reference images and
returns the best match score.

Reference image hashes are pre-computed once per source and cached
across all candidates to avoid redundant downloads and hashing.
"""

from __future__ import annotations

import logging

import imagehash

from .base import BaseSignal, SignalResult
from ._http import download_image

log = logging.getLogger(__name__)

# Max hamming distance for a 64-bit hash (8x8 image → 64 bits)
_MAX_DISTANCE = 64

# Cache reference hashes keyed by frozenset of image URLs
_ref_hash_cache: dict[frozenset[str], list[tuple[str, object, object]]] = {}


def _hash_distance_score(hash_a, hash_b) -> float:
    """Convert hamming distance to a 0-1 similarity score."""
    dist = hash_a - hash_b  # imagehash overloads __sub__ as hamming distance
    return max(0.0, 1.0 - dist / _MAX_DISTANCE)


class ImageHashSignal(BaseSignal):
    """Compare candidate image against ALL source reference images using perceptual hashes.

    Uses both pHash (frequency-domain, robust to scaling/compression) and
    dHash (gradient-based, robust to brightness changes). Compares the candidate
    against every reference image and returns the best match score.
    """

    name = "image_similarity"
    default_weight = 0.15

    def __init__(self, hash_size: int = 8):
        self._hash_size = hash_size

    async def _get_ref_hashes(self, image_urls: list[str]) -> list[tuple[str, object, object]]:
        """Download and hash reference images, caching the result."""
        cache_key = frozenset(image_urls)
        if cache_key in _ref_hash_cache:
            return _ref_hash_cache[cache_key]

        hashes = []
        for url in image_urls:
            img = await download_image(url)
            if img is None:
                continue
            ph = imagehash.phash(img, hash_size=self._hash_size)
            dh = imagehash.dhash(img, hash_size=self._hash_size)
            hashes.append((url, ph, dh))

        _ref_hash_cache[cache_key] = hashes
        return hashes

    async def compute(self, source: dict, candidate: dict) -> SignalResult:
        src_images = source.get("images", [])
        cand_url = candidate.get("image_url", "")

        if not src_images or not cand_url:
            return SignalResult(
                name=self.name,
                score=0.0,
                weight=self.default_weight,
                raw={"note": "missing image URL", "source_count": len(src_images), "candidate_url": cand_url},
                reason="Cannot compare — missing image",
            )

        cand_img = await download_image(cand_url)
        if cand_img is None:
            return SignalResult(
                name=self.name,
                score=0.0,
                weight=self.default_weight,
                raw={"note": "failed to download candidate image"},
                reason="Image download failed (candidate)",
            )

        cand_phash = imagehash.phash(cand_img, hash_size=self._hash_size)
        cand_dhash = imagehash.dhash(cand_img, hash_size=self._hash_size)

        # Get pre-computed reference hashes (cached across candidates)
        ref_hashes = await self._get_ref_hashes(src_images)

        if not ref_hashes:
            return SignalResult(
                name=self.name,
                score=0.0,
                weight=self.default_weight,
                raw={"note": "failed to download any reference images"},
                reason="Image download failed (all reference images)",
            )

        # Compare against all cached reference hashes, keep the best match
        best_score = 0.0
        best_phash_dist = _MAX_DISTANCE
        best_dhash_dist = _MAX_DISTANCE
        best_ref_url = ""

        for ref_url, ref_phash, ref_dhash in ref_hashes:
            phash_score = _hash_distance_score(ref_phash, cand_phash)
            dhash_score = _hash_distance_score(ref_dhash, cand_dhash)
            match_score = max(phash_score, dhash_score)

            if match_score > best_score:
                best_score = match_score
                best_phash_dist = ref_phash - cand_phash
                best_dhash_dist = ref_dhash - cand_dhash
                best_ref_url = ref_url

        refs_checked = len(ref_hashes)
        score = round(best_score, 4)

        if score >= 0.85:
            reason = f"Images very similar (pHash dist={best_phash_dist}, dHash dist={best_dhash_dist}, best of {refs_checked} refs)"
        elif score >= 0.65:
            reason = f"Images moderately similar (pHash dist={best_phash_dist}, dHash dist={best_dhash_dist}, best of {refs_checked} refs)"
        else:
            reason = f"Images differ significantly (pHash dist={best_phash_dist}, dHash dist={best_dhash_dist}, best of {refs_checked} refs)"

        return SignalResult(
            name=self.name,
            score=score,
            weight=self.default_weight,
            raw={
                "best_phash_distance": best_phash_dist,
                "best_dhash_distance": best_dhash_dist,
                "best_ref_url": best_ref_url,
                "refs_checked": refs_checked,
                "refs_total": len(src_images),
            },
            reason=reason,
        )
