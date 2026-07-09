"""Adapters for raw input images (PIL, tifffile, bathymetry → ocean mask)."""

import logging
import re
from pathlib import Path

import numpy as np
import tifffile
from PIL import Image

from . import config
from .encoding import linear_to_srgb

log = logging.getLogger(__name__)

Image.MAX_IMAGE_PIXELS = None

_NODATA_THRESHOLD = -1e31  # GDAL nodata for float TIFFs is -1e+32

# Native height unit → kilometres. USGS planetary DEMs are metres; the SVS
# LOLA float map is already km; the SVS uint variant is half-metres.
_HEIGHT_UNIT_KM = {"m": 1e-3, "km": 1.0, "half_m": 5e-4}

# Output rows per streaming band in open_displacement_source — caps the
# per-band working set (~650 MiB float32 at ds=6 on a 100k-wide DEM).
_DISPLACEMENT_BAND_OUT_ROWS = 256


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


def _gdal_scale_offset(page: tifffile.TiffPage) -> tuple[float, float]:
    """GDAL raw→native (scale, offset) from GDAL_METADATA; identity if absent."""
    tag = page.tags.get("GDAL_METADATA")
    scale, offset = 1.0, 0.0
    if tag and isinstance(tag.value, str):
        if m := re.search(r'role="scale">\s*([-\d.eE+]+)', tag.value):
            scale = float(m.group(1))
        if m := re.search(r'role="offset">\s*([-\d.eE+]+)', tag.value):
            offset = float(m.group(1))
    return scale, offset


def _gdal_nodata(page: tifffile.TiffPage) -> float | None:
    tag = page.tags.get("GDAL_NODATA")
    if tag and tag.value is not None:
        try:
            return float(tag.value)
        except (TypeError, ValueError):
            return None
    return None


# PDS3/ISIS2 CORE_ITEM_TYPE → numpy dtype (big/little-endian IEEE reals). ISIS
# special pixels (nulls, saturations) live near -3.4e38 and fall to the shared
# _NODATA_THRESHOLD guard, so no explicit nodata is needed.
_ISIS_REAL_DTYPE = {
    ("SUN_REAL", 4): ">f4",
    ("MSB_IEEE_REAL", 4): ">f4",
    ("IEEE_REAL", 4): ">f4",
    ("PC_REAL", 4): "<f4",
    ("LSB_IEEE_REAL", 4): "<f4",
}


def _isis_label_value(label: str, key: str) -> str | None:
    m = re.search(rf"^\s*{re.escape(key)}\s*=\s*(.+?)\s*$", label, re.MULTILINE)
    return m.group(1) if m else None


def _open_isis_cube(src: Path) -> tuple[np.ndarray, float, float, float | None]:
    """Memory-map a single-band ISIS2/PDS3 QUBE cube as a 2-D height array.

    Reads the ASCII PVL label to locate the raw core (``^QUBE`` record,
    ``RECORD_BYTES``), its dtype (``CORE_ITEM_TYPE``/``CORE_ITEM_BYTES``), and
    the raw→native ``CORE_BASE``/``CORE_MULTIPLIER``. Returns (memmap, scale,
    offset, nodata=None) mirroring the GeoTIFF path.
    """
    with src.open("rb") as fh:
        label = fh.read(1 << 16).decode("latin-1", "replace")

    def need(key: str) -> str:
        val = _isis_label_value(label, key)
        if val is None:
            raise ValueError(f"{src.name}: missing ISIS label key {key}")
        return val

    record_bytes = int(need("RECORD_BYTES"))
    qube_record = int(need("^QUBE"))
    item_type = need("CORE_ITEM_TYPE").strip().strip('"')
    item_bytes = int(need("CORE_ITEM_BYTES"))
    samples, lines, bands = (
        int(x) for x in re.findall(r"-?\d+", need("CORE_ITEMS"))[:3]
    )
    if bands != 1:
        raise ValueError(f"{src.name}: expected 1-band cube, got {bands}")
    dtype = _ISIS_REAL_DTYPE.get((item_type, item_bytes))
    if dtype is None:
        raise ValueError(f"{src.name}: unsupported CORE_ITEM_TYPE {item_type!r}")

    base = float(_isis_label_value(label, "CORE_BASE") or 0.0)
    multiplier = float(_isis_label_value(label, "CORE_MULTIPLIER") or 1.0)
    offset_bytes = (qube_record - 1) * record_bytes
    mm = np.memmap(
        src, dtype=dtype, mode="r", offset=offset_bytes, shape=(lines, samples)
    )
    return mm, multiplier, base, None


def open_displacement_source(
    src: Path,
    *,
    unit: str = "m",
    scale: float | None = None,
    offset: float | None = None,
    nodata: float | None = None,
    nodata_fill_km: float | None = None,
) -> tuple[Image.Image, float, float]:
    """DEM/height source → 8-bit grayscale tile + the km range it encodes.

    Reads GeoTIFFs (GDAL tags) and single-band ISIS2/PDS3 cubes. Value km =
    ``(raw·scale + offset)·unit→km`` — elevation for most DEMs, or absolute
    radius for those that store it (the renderer subtracts its sphere radius
    then). scale/offset/nodata default to the file's tags, overridable per
    entry. ``nodata_fill_km`` sets the elevation gaps sink to (default: the
    lowest valid terrain; partial-coverage DEMs pass 0 to rest at the datum).
    Returns the tile + the km at texel 0 and 255 so the renderer scales
    displacement to true relief.
    """
    if unit not in _HEIGHT_UNIT_KM:
        raise ValueError(f"{src.name}: unknown height_unit {unit!r}")
    unit_km = _HEIGHT_UNIT_KM[unit]

    if src.suffix.lower() in (".cub", ".cube"):
        mm, f_scale, f_offset, f_nodata = _open_isis_cube(src)
        return _bake_displacement(
            mm,
            src.name,
            scale=f_scale if scale is None else scale,
            offset=f_offset if offset is None else offset,
            nodata=f_nodata if nodata is None else nodata,
            unit_km=unit_km,
            nodata_fill_km=nodata_fill_km,
        )

    with tifffile.TiffFile(str(src)) as tif:
        page = tif.pages[0]
        assert isinstance(page, tifffile.TiffPage)  # page 0 is always a full page
        g_scale, g_offset = _gdal_scale_offset(page)
        g_nodata = _gdal_nodata(page) if nodata is None else nodata
        if page.is_contiguous:
            mm = page.asarray(out="memmap")
        else:
            # Only memmappable sources stream; the rest are small enough to fit.
            log.info("%s not contiguous; full-loading instead of streaming", src.name)
            mm = page.asarray()
        return _bake_displacement(
            mm,
            src.name,
            scale=g_scale if scale is None else scale,
            offset=g_offset if offset is None else offset,
            nodata=g_nodata,
            unit_km=unit_km,
            nodata_fill_km=nodata_fill_km,
        )


def _bake_displacement(
    mm: np.ndarray,
    src_name: str,
    *,
    scale: float,
    offset: float,
    nodata: float | None,
    unit_km: float,
    nodata_fill_km: float | None,
) -> tuple[Image.Image, float, float]:
    """Box-average a memmapped height array to an 8-bit tile + its km range.

    Memory-mapped and box-averaged in row-bands so peak RAM stays near one
    band: the Mars blend is 10.6 GiB int16 and a whole-image float64 expansion
    would need ~43 GiB. Integer pre-downsampling is free since exports cap at
    ``WEBP_MAX`` anyway; LANCZOS does the final resize.
    """
    if mm.ndim != 2:
        raise ValueError(
            f"{src_name}: expected single-channel height map, got {mm.shape}"
        )
    src_h, src_w = mm.shape

    # Box-average factor landing the longest side just above the export
    # ceiling; ds=1 keeps full res but still streams band-wise.
    ds = max(1, max(src_w, src_h) // config.WEBP_MAX)
    out_w, out_h = src_w // ds, src_h // ds
    if ds > 1:
        log.info(
            "%s: streaming %dx%d → %dx%d (%dx box-average)",
            src_name,
            src_w,
            src_h,
            out_w,
            out_h,
            ds,
        )

    # Fully-nodata blocks land as NaN, filled after the range is known.
    out_elev = np.empty((out_h, out_w), dtype=np.float32)
    crop_w = out_w * ds  # drop the ≤ds-1 ragged edge cols
    for oy0 in range(0, out_h, _DISPLACEMENT_BAND_OUT_ROWS):
        oy1 = min(oy0 + _DISPLACEMENT_BAND_OUT_ROWS, out_h)
        bh = oy1 - oy0
        raw = np.asarray(mm[oy0 * ds : oy1 * ds, :crop_w]).astype(np.float32)
        valid = np.isfinite(raw) & (raw > _NODATA_THRESHOLD)
        if nodata is not None:
            valid &= raw != nodata
        elev = (raw * scale + offset) * unit_km
        elev[~valid] = 0.0
        blocks = (bh, ds, out_w, ds)
        sums = elev.reshape(blocks).sum(axis=(1, 3))
        counts = valid.reshape(blocks).sum(axis=(1, 3))
        out_elev[oy0:oy1] = np.where(counts > 0, sums / np.maximum(counts, 1), np.nan)
    del mm

    finite = np.isfinite(out_elev)
    if finite.any():
        lo = float(out_elev[finite].min())
        hi = float(out_elev[finite].max())
    else:
        log.warning("%s: no valid height pixels; defaulting flat", src_name)
        lo, hi = 0.0, 1.0
    # Gaps sink to the lowest terrain by default; partial-coverage DEMs pass a
    # datum-relative fill (0 km) so unmapped regions rest at the reference
    # ellipsoid instead of the deepest basin.
    fill = lo if nodata_fill_km is None else nodata_fill_km
    n_gap = int((~finite).sum())
    if n_gap:
        log.info(
            "%s: %d/%d output px unmapped, filled at %.3f km",
            src_name,
            n_gap,
            out_elev.size,
            fill,
        )
    out_elev[~finite] = fill
    norm = np.clip((out_elev - lo) / max(hi - lo, 1e-6), 0.0, 1.0)
    gray = (norm * 255.0).astype(np.uint8)
    return Image.fromarray(gray, mode="L").convert("RGB"), lo, hi


def open_premade_specular_source(src: Path) -> Image.Image:
    """Load a ready-made specular/roughness map as-is (grayscale → RGB).

    Unlike open_specular_source, no thresholding: the source is already a mask
    where bright = specular (e.g. Titan's hydrocarbon seas), so it feeds the
    renderer's roughness slot directly.
    """
    return Image.open(src).convert("L").convert("RGB")


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
