"""WebP save logic and size helpers — pure pixel work, no project state."""

import logging
from pathlib import Path

import numpy as np
from PIL import Image

from . import config

log = logging.getLogger(__name__)


def linear_to_srgb(x: np.ndarray) -> np.ndarray:
    """Peicewise sRGB EOTF — linear toe + power curve."""
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def webp_kwargs(lossless: bool) -> dict:
    return {"lossless": True, "method": 6} if lossless else {"quality": 80}


def tier_for_size(size: int) -> str:
    for dim, tier, _ in config.SIZE_TARGETS:
        if size <= dim:
            return tier
    return "high"


def size_target(export_dim: int) -> int | None:
    for dim, _, target in config.SIZE_TARGETS:
        if export_dim <= dim:
            return target
    return None


def resize(img: Image.Image, max_dim: int) -> Image.Image:
    w, h = img.size
    scale = max_dim / max(w, h)
    return img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)


def save_webp(
    img: Image.Image,
    path: Path,
    lossless: bool,
    max_bytes: int | None = config.MAX_FILE_BYTES,
) -> dict:
    """Save ``img`` as WebP, honoring an optional hard size cap.

    When ``max_bytes`` is set and the lossy save exceeds it, quality is dropped
    in steps of 10 (down to ``MIN_QUALITY``); if that's still not enough the
    image is resized down by ``SHRINK_RATIO`` and quality resets to 80.
    Repeats until the file fits or the longest side would fall below
    ``MIN_DIM_AFTER_SHRINK`` (at which point we give up and keep the last
    best-effort output). Lossless saves skip the degradation loop — if a
    lossless save overflows the cap the caller needs to downsize the source.
    """
    if lossless or max_bytes is None:
        img.save(path, "webp", **webp_kwargs(lossless))
        size = path.stat().st_size
        if max_bytes is not None and size > max_bytes:
            log.warning(
                "%s lossless exceeds cap: %.1f MiB > %.1f MiB",
                path.name,
                size / 1024 / 1024,
                max_bytes / 1024 / 1024,
            )
        log.debug(
            "saved %s (%dx%d, %.1f KiB)", path.name, img.width, img.height, size / 1024
        )
        return {
            "file": path.name,
            "width": img.width,
            "height": img.height,
            "size_bytes": size,
            "lossless": lossless,
        }

    # Lossy with a hard cap — iteratively degrade quality then dimensions.
    current = img
    quality = 80
    size = 0
    while True:
        current.save(path, "webp", quality=quality)
        size = path.stat().st_size
        if size <= max_bytes:
            break
        if quality > config.MIN_QUALITY:
            quality -= 10
            continue
        # Hit the quality floor; shrink by SHRINK_RATIO and retry at q=80.
        new_dim = int(max(current.size) * config.SHRINK_RATIO)
        if new_dim < config.MIN_DIM_AFTER_SHRINK:
            log.error(
                "%s cannot fit under %.1f MiB cap (last: %.1f MiB at %dx%d q=%d)",
                path.name,
                max_bytes / 1024 / 1024,
                size / 1024 / 1024,
                current.width,
                current.height,
                quality,
            )
            break
        log.info(
            "%s over cap at %dx%d q=%d (%.1f MiB), shrinking to %d px",
            path.name,
            current.width,
            current.height,
            quality,
            size / 1024 / 1024,
            new_dim,
        )
        current = resize(current, new_dim)
        quality = 80

    if current is not img:
        log.warning(
            "%s downsized to %dx%d q=%d to fit cap (source was %dx%d)",
            path.name,
            current.width,
            current.height,
            quality,
            img.width,
            img.height,
        )
    elif quality < 80:
        log.info(
            "%s re-encoded at q=%d (%.1f MiB) to fit cap",
            path.name,
            quality,
            size / 1024 / 1024,
        )

    log.debug(
        "saved %s (%dx%d, %.1f KiB)",
        path.name,
        current.width,
        current.height,
        size / 1024,
    )
    rec: dict = {
        "file": path.name,
        "width": current.width,
        "height": current.height,
        "size_bytes": size,
        "lossless": False,
    }
    if quality != 80:
        rec["quality"] = quality
    return rec
