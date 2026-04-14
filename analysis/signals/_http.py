"""Shared HTTP utilities for image signals."""

from __future__ import annotations

import io
import logging

import httpx
from PIL import Image

log = logging.getLogger(__name__)


async def download_image(url: str, timeout: float = 10.0) -> Image.Image | None:
    """Download image from URL, return PIL Image or None on failure."""
    if not url:
        return None
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return Image.open(io.BytesIO(resp.content)).convert("RGB")
    except Exception as e:
        log.debug("Failed to download image %s: %s", url, e)
        return None
