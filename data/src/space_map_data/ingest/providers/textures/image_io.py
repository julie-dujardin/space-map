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


def open_displacement_source(src: Path) -> tuple[Image.Image, float, float]:
    """Load an LRO LOLA height map and stretch it to an 8-bit grayscale tile.

    The reference surface for LOLA is a sphere of radius 1737.4 km; gridded
    elevations are signed 16-bit half-meters relative to it. The SVS TIFFs
    encode that two ways, distinguished by filename:
    - float (``ldem_*.tif``): the value already *is* elevation in km;
    - unsigned 16-bit (``ldem_*_uint.tif``): half-meters offset by +20000
      (10 km) to stay positive, so km = (value - 20000) / 2000.

    Returns the RGB-promoted mask plus the elevation (km) that pixel 0 and 255
    map to, so the renderer can reconstruct true-to-scale radial offsets. The
    8-bit stretch quantises ~20 km of relief into 256 steps (~78 m), which is
    well under the lunar limb's visible scale.
    """
    arr = tifffile.imread(str(src))
    if arr.ndim != 2:
        raise ValueError(
            f"{src.name}: expected single-channel height map, got {arr.shape}"
        )

    if src.stem.endswith("_uint"):
        elev_km = (arr.astype(np.float64) - 20000.0) / 2000.0
    else:
        elev_km = arr.astype(np.float64)

    valid = elev_km > _NODATA_THRESHOLD
    lo = float(elev_km[valid].min()) if valid.any() else 0.0
    hi = float(elev_km[valid].max()) if valid.any() else 1.0
    norm = np.clip((elev_km - lo) / max(hi - lo, 1e-6), 0.0, 1.0)
    gray = (norm * 255.0).astype(np.uint8)
    return Image.fromarray(gray, mode="L").convert("RGB"), lo, hi


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
