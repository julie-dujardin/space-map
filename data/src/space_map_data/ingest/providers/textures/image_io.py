"""Adapters for raw input images (PIL, tifffile, bathymetry → ocean mask)."""

import logging
from pathlib import Path

import numpy as np
import tifffile
from PIL import Image

from .encoding import linear_to_srgb

log = logging.getLogger(__name__)

Image.MAX_IMAGE_PIXELS = None

_NODATA_THRESHOLD = -1e31  # GDAL nodata for float TIFFs is -1e+32


def open_image(path: Path) -> Image.Image:
    try:
        img = Image.open(path)
    except Exception:
        log.debug(
            "PIL could not open %s, falling back to tifffile", path.name, exc_info=True
        )
    else:
        if img.mode != "RGB":
            log.info("converting %s from %s to RGB", path.name, img.mode)
            img = img.convert("RGB")
        return img

    arr = tifffile.imread(str(path))
    if arr.dtype.kind != "f":
        raise ValueError(f"tifffile loaded {path.name} as {arr.dtype}, expected float")

    # Promote single-channel (H, W) so the channel-aware logic below works.
    if arr.ndim == 2:
        arr = arr[..., None]

    nodata_mask = arr < _NODATA_THRESHOLD
    arr = np.clip(arr, 0.0, None)
    arr[nodata_mask] = 0.0
    arr = arr.astype(np.float32)

    # Joint stretch: single (lo, hi) across all channels preserves color ratios
    valid_mask = ~nodata_mask.any(axis=-1)
    valid_px = arr[valid_mask]
    lo = np.percentile(valid_px, 2) if valid_px.size else 0.0
    hi = np.percentile(valid_px, 98) if valid_px.size else 1.0
    arr = np.clip((arr - lo) / max(hi - lo, 1e-6), 0.0, 1.0)

    arr = linear_to_srgb(arr)

    arr = (arr * 255.0).astype(np.uint8)
    if arr.shape[-1] == 1:
        log.info("broadcasting single-channel %s to RGB", path.name)
        arr = np.repeat(arr, 3, axis=-1)
    if arr.ndim != 3 or arr.shape[-1] != 3:
        raise ValueError(
            f"{path.name}: expected an (H, W, 3) RGB array but got shape {arr.shape}."
        )
    return Image.fromarray(arr, mode="RGB")


def open_specular_source(src: Path) -> Image.Image:
    """Derive a binary ocean mask from a bathymetry TIFF.

    GEBCO's bathymetry stores land as 255 (the nodata mask) and ocean as
    grayscale by depth. The output is a single-channel mask with land at 0
    (matte) and ocean at 255 (full specular). Any pixel within a couple of
    levels of pure white is treated as land so antialiased coastlines don't
    leak into the ocean mask.
    """
    img = Image.open(src).convert("L")
    arr = np.asarray(img)
    mask = np.where(arr >= 254, 0, 255).astype(np.uint8)
    # WebP saves don't support single-channel mode in Pillow; promote to RGB.
    # The triplicated payload still compresses to near-zero (the mask is flat
    # binary), so the size growth is negligible.
    return Image.fromarray(mask, mode="L").convert("RGB")
