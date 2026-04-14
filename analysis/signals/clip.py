"""CLIP image embedding similarity signal.

Uses open_clip ViT-B-32 to compute cosine similarity between candidate
and ALL source reference product images. Returns the best match.
More robust than perceptual hashing for cases where products look similar
but aren't pixel-identical.

Reference image embeddings are pre-computed once per source and cached
across all candidates to avoid redundant downloads and model inference.
"""

from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np
import torch
from PIL import Image

from .base import BaseSignal, SignalResult
from ._http import download_image

log = logging.getLogger(__name__)

# Cache reference embeddings keyed by frozenset of image URLs
_ref_cache: dict[frozenset[str], list[tuple[str, np.ndarray]]] = {}


@lru_cache(maxsize=1)
def _load_model():
    """Load CLIP model once and cache it."""
    import open_clip

    model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-B-32", pretrained="laion2b_s34b_b79k"
    )
    model.eval()
    return model, preprocess


def _embed_image(img: Image.Image) -> np.ndarray:
    """Compute normalized CLIP embedding for a PIL image."""
    model, preprocess = _load_model()
    tensor = preprocess(img).unsqueeze(0)
    with torch.no_grad():
        features = model.encode_image(tensor)
    features = features / features.norm(dim=-1, keepdim=True)
    return features.squeeze().cpu().numpy()


async def _get_ref_embeddings(image_urls: list[str]) -> list[tuple[str, np.ndarray]]:
    """Download and embed reference images, caching the result."""
    cache_key = frozenset(image_urls)
    if cache_key in _ref_cache:
        return _ref_cache[cache_key]

    embeddings = []
    for url in image_urls:
        img = await download_image(url)
        if img is None:
            continue
        try:
            emb = _embed_image(img)
            embeddings.append((url, emb))
        except Exception as e:
            log.debug("CLIP embedding failed for ref %s: %s", url, e)

    _ref_cache[cache_key] = embeddings
    return embeddings


class CLIPSimilaritySignal(BaseSignal):
    """Compare candidate image against ALL source reference images using CLIP embeddings.

    Cosine similarity in CLIP space captures semantic similarity —
    two photos of the same sneaker from different angles will score high,
    while a sneaker vs a shirt will score low. Compares against all reference
    images and returns the best match.
    """

    name = "clip_similarity"
    default_weight = 0.10

    async def compute(self, source: dict, candidate: dict) -> SignalResult:
        src_images = source.get("images", [])
        cand_url = candidate.get("image_url", "")

        if not src_images or not cand_url:
            return SignalResult(
                name=self.name,
                score=0.0,
                weight=self.default_weight,
                raw={"note": "missing image URL"},
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

        try:
            cand_emb = _embed_image(cand_img)
        except Exception as e:
            log.warning("CLIP embedding failed for candidate: %s", e)
            return SignalResult(
                name=self.name,
                score=0.0,
                weight=self.default_weight,
                raw={"error": str(e)},
                reason="CLIP model error",
            )

        # Get pre-computed reference embeddings (cached across candidates)
        ref_embeddings = await _get_ref_embeddings(src_images)

        if not ref_embeddings:
            return SignalResult(
                name=self.name,
                score=0.0,
                weight=self.default_weight,
                raw={"note": "failed to process any reference images"},
                reason="CLIP: could not embed any reference images",
            )

        # Compare against all cached reference embeddings
        best_cosine = -1.0
        best_ref_url = ""

        for ref_url, ref_emb in ref_embeddings:
            cosine = float(np.dot(ref_emb, cand_emb))
            if cosine > best_cosine:
                best_cosine = cosine
                best_ref_url = ref_url

        refs_checked = len(ref_embeddings)

        # Map cosine to score: CLIP cosine for same-product images is typically 0.7-0.95
        # Different products: 0.2-0.5. We rescale to make it more discriminative.
        score = max(0.0, min(1.0, (best_cosine - 0.3) / 0.5))

        if score >= 0.8:
            reason = f"CLIP: images semantically very similar (cosine={best_cosine:.3f}, best of {refs_checked} refs)"
        elif score >= 0.5:
            reason = f"CLIP: moderate image similarity (cosine={best_cosine:.3f}, best of {refs_checked} refs)"
        else:
            reason = f"CLIP: images look different (cosine={best_cosine:.3f}, best of {refs_checked} refs)"

        return SignalResult(
            name=self.name,
            score=round(score, 4),
            weight=self.default_weight,
            raw={
                "best_cosine_similarity": round(best_cosine, 4),
                "best_ref_url": best_ref_url,
                "refs_checked": refs_checked,
                "refs_total": len(src_images),
            },
            reason=reason,
        )
