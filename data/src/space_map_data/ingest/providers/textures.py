import gc
import json
import logging
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict, cast

import Imath
import numpy as np
import OpenEXR  # ty: ignore[unresolved-import]  # C extension, no stubs
import py360convert
import tifffile
import yaml
from PIL import Image

from space_map_data.export.sidecar_io import mirror_path
from space_map_data.models.object import Object
from space_map_data.utils.db import get_session
from space_map_data.utils.paths import DOWNLOAD_DIR, EXPORT_DIR

Image.MAX_IMAGE_PIXELS = None

log = logging.getLogger(__name__)

RAW_DIR = DOWNLOAD_DIR / "textures" / "raw"
# Per-asset subdirs under `misc/` carry their own download-metadata.yaml; used
# for manually downloaded files (e.g. GEBCO bathymetry) that don't flow through
# the auto-downloader. TextureProcessor merges every misc/*/download-metadata.yaml
# into the main bodies list at startup.
MISC_DIR = DOWNLOAD_DIR / "textures" / "misc"
PROCESSED_DIR = EXPORT_DIR / "v1" / "textures"
# Per-texture scraped source metadata (written by the texture_sources downloader);
# used as a fallback for `attribution` when download-metadata.yaml doesn't provide one.
SOURCE_METADATA_PARSED_DIR = DOWNLOAD_DIR / "textures" / "source_metadata" / "parsed"
# Date-partitioned snapshots written by the earth_clouds downloader at 3h cadence.
EARTH_CLOUDS_DIR = DOWNLOAD_DIR / "textures" / "earth_clouds"
# Parallel to the Earth surface texture; the renderer layers it on top of naif-399.
EARTH_CLOUDS_OBJECT_ID = "naif-399_clouds"
# Suffix on the export directory holding a body's specular/roughness bundle —
# sibling of the surface texture, mirrors the `_clouds` convention.
SPECULAR_SUFFIX = "_specular"

# Cubemap face order, matching Three.js' CubeTextureLoader expectation
# (+X, -X, +Y, -Y, +Z, -Z).
SKYBOX_FACES = ("px", "nx", "py", "ny", "pz", "nz")
# py360convert.e2c with cube_format="dict" returns Front/Right/Back/Left/Up/Down
# keys (yaw=0 → F; +x → R; +y → U; etc.). This maps each onto its WebGL axis
# label so the on-disk filenames stay aligned with cubemap-sampler conventions.
# Renderer-side RA/dec orientation can apply a rotation if needed.
_PY360_TO_FACE = {"R": "px", "L": "nx", "U": "py", "D": "ny", "F": "pz", "B": "nz"}
# Per-face edge length for each tier. UASTC 4K/face would be the eventual
# target; for WebP we keep the same dims and rely on the size cap.
SKYBOX_TIER_SIZES = {"low": 2048, "high": 4096}
# Exposure pre-multiplier applied before Reinhard tonemap. The SVS Deep Star
# Maps EXR has bright stars sitting well above 1.0; bumping exposure brings
# the Milky Way out of the toe before the tonemap squashes the dynamic range.
SKYBOX_EXPOSURE = 4.0

WEBP_MAX = 16383  # WebP hard limit per dimension
EXPORT_SIZES = [2048, 8192]  # intermediate sizes to generate for large images

# Upper-bound lookup: (max_dim, tier_name, size_target)
SIZE_TARGETS = [
    (2048, "low", 300 * 1024),
    (8192, "medium", 2 * 1024 * 1024),
    (WEBP_MAX, "high", 6 * 1024 * 1024),
]

# Hard file-size cap, enforced after save. Cloudflare Pages rejects individual
# files over 25 MiB, so high-detail textures (Mercury MDIS, Bennu, Mars Viking)
# need to shrink or re-encode at lower quality to land below this. 23 MiB
# leaves 2 MiB of headroom for upload-wrapper overhead.
MAX_FILE_BYTES = 24 * 1024 * 1024
MIN_QUALITY = 60  # webp artifacts become visible on textures below this
SHRINK_RATIO = 0.85  # how much to downscale per iteration when quality floor is hit
MIN_DIM_AFTER_SHRINK = 4096  # stop shrinking below this — below the medium tier


_NODATA_THRESHOLD = -1e31  # GDAL nodata for float TIFFs is -1e+32


def _linear_to_srgb(x: np.ndarray) -> np.ndarray:
    """Peicewise sRGB EOTF — linear toe + power curve."""
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def _open_image(path: Path) -> Image.Image:
    try:
        return Image.open(path)
    except Exception:
        log.debug(
            "PIL could not open %s, falling back to tifffile", path.name, exc_info=True
        )

    arr = tifffile.imread(str(path))
    if arr.dtype.kind != "f":
        raise ValueError(f"tifffile loaded {path.name} as {arr.dtype}, expected float")

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

    arr = _linear_to_srgb(arr)

    arr = (arr * 255.0).astype(np.uint8)
    return Image.fromarray(arr, mode="RGB")


def _mem_available_bytes() -> int | None:
    """Return MemAvailable from /proc/meminfo in bytes, or None if unreadable.

    Used as a coarse pre-flight check before loading multi-gigabyte EXRs.
    Returns None on non-Linux platforms or if the file is missing — callers
    treat None as "don't know, proceed".
    """
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    parts = line.split()
                    return int(parts[1]) * 1024  # kB → bytes
    except OSError:
        return None
    return None


# Source-to-output downsample ratio applied while streaming the EXR. The
# SVS Deep Star Maps 2020 source is 65536×32768 — far above what a 4K-per-face
# cubemap can resolve. Box-averaging 4:1 in each axis lands the working
# equirect at 16384×8192 (~45 px/deg), matching a 4K cube face's angular
# sampling density and keeping the uint8 buffer at ~384 MiB.
_SKYBOX_DOWNSAMPLE = 4
# Number of *output* rows tonemapped per streaming band. At 16K output width
# with 4× downsample, each band reads 256×4 = 1024 source scanlines per
# channel (~128 MiB of half-float source data per band).
_SKYBOX_BAND_OUT_ROWS = 256


def _load_and_tonemap_skybox_streaming(src: Path) -> np.ndarray:
    """Stream-read an HDR equirect EXR and tonemap to a downsampled uint8 equirect.

    Returns (H/ds, W/ds, 3) uint8 in sRGB-encoded values, where ``ds`` is
    ``_SKYBOX_DOWNSAMPLE``. Reads source scanlines in chunks via OpenEXR's
    ``InputFile.channel`` so peak working memory stays well under the full
    uncompressed pixel size (12+ GiB for 64K×32K half-float).

    The Reinhard tonemap with exposure pre-multiplier (``SKYBOX_EXPOSURE``)
    lifts faint Milky Way structure above the toe before compression to
    [0, 1). sRGB encoding follows so the resulting WebP samples correctly
    under Three.js' default sRGB texture path.
    """
    inp = OpenEXR.InputFile(str(src))
    hdr = inp.header()
    dw = hdr["dataWindow"]
    src_w = dw.max.x - dw.min.x + 1
    src_h = dw.max.y - dw.min.y + 1
    ds = _SKYBOX_DOWNSAMPLE
    if src_w % ds or src_h % ds:
        raise ValueError(
            f"{src.name}: dims {src_w}x{src_h} not divisible by downsample {ds}"
        )
    out_w, out_h = src_w // ds, src_h // ds
    out = np.empty((out_h, out_w, 3), dtype=np.uint8)
    pt = Imath.PixelType(Imath.PixelType.HALF)

    log.info(
        "streaming EXR %dx%d → %dx%d uint8 (%dx downsample, %d bands)",
        src_w,
        src_h,
        out_w,
        out_h,
        ds,
        (out_h + _SKYBOX_BAND_OUT_ROWS - 1) // _SKYBOX_BAND_OUT_ROWS,
    )

    for out_y0 in range(0, out_h, _SKYBOX_BAND_OUT_ROWS):
        out_y1 = min(out_y0 + _SKYBOX_BAND_OUT_ROWS, out_h)
        band_out_h = out_y1 - out_y0
        src_y0 = out_y0 * ds
        src_y1 = src_y0 + band_out_h * ds - 1  # inclusive

        channels: list[np.ndarray] = []
        for name in ("R", "G", "B"):
            raw = inp.channel(name, pt, src_y0, src_y1)
            ch = np.frombuffer(raw, dtype=np.float16).reshape(band_out_h * ds, src_w)
            channels.append(ch)

        # Stack and box-average ds×ds blocks. Cast to float32 first so
        # bright-star half-float values aggregate without saturation bias.
        rgb_src = np.stack(channels, axis=-1).astype(np.float32, copy=False)
        del channels
        band = rgb_src.reshape(band_out_h, ds, out_w, ds, 3).mean(
            axis=(1, 3), dtype=np.float32
        )
        del rgb_src

        np.multiply(band, SKYBOX_EXPOSURE, out=band)
        np.clip(band, 0.0, None, out=band)
        denom = band + 1.0
        np.divide(band, denom, out=band)
        del denom
        srgb = _linear_to_srgb(band)
        np.clip(srgb, 0.0, 1.0, out=srgb)
        np.multiply(srgb, 255.0, out=srgb)
        np.add(srgb, 0.5, out=srgb)
        out[out_y0:out_y1] = srgb.astype(np.uint8, copy=False)
        del band, srgb

    inp.close()
    return out


def _alignment(entry: dict) -> dict:
    """Extract cylindrical-alignment fields from a yaml entry.

    Defaults match the renderer's expected convention (no flip, prime
    meridian at the image centre) so untagged entries are no-ops.
    """
    return {
        "west_positive": bool(entry.get("west_positive", False)),
        "lon_at_left_deg": float(entry.get("lon_at_left_deg", -180.0)),
    }


_DEFAULT_ALIGNMENT = {"west_positive": False, "lon_at_left_deg": -180.0}


def _align_cylindrical(
    img: Image.Image, *, west_positive: bool, lon_at_left_deg: float
) -> Image.Image:
    """Transform a cylindrical equirectangular image to the renderer's convention.

    The renderer (frontend/src/lib/math/orientation.ts) expects u=0 at
    longitude -180°, u=0.5 at 0° (prime meridian), and longitude increasing
    east with u.

    Two corrections applied in order:
      1. ``west_positive``: horizontally mirror W+ IAU sources (Jovian /
         Saturnian satellites, gas giants under System III) so the result is
         east-positive.
      2. ``lon_at_left_deg``: east-positive longitude at the source's left
         edge *after* any flip. The image is circularly shifted so this lands
         at -180°. Default -180° → no shift.
    """
    if west_positive:
        img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)

    w, h = img.size
    shift_px = round((lon_at_left_deg + 180.0) / 360.0 * w) % w
    if shift_px == 0:
        return img

    left = img.crop((0, 0, w - shift_px, h))
    right = img.crop((w - shift_px, 0, w, h))
    out = Image.new(img.mode, (w, h))
    out.paste(right, (0, 0))
    out.paste(left, (shift_px, 0))
    return out


def _open_specular_source(src: Path) -> Image.Image:
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


def _webp_kwargs(lossless: bool) -> dict:
    return {"lossless": True, "method": 6} if lossless else {"quality": 80}


def _refresh_metadata_from_yaml(out_dir: Path, entry: dict, src_file_name: str) -> None:
    """Update yaml-sourced fields on an existing metadata.json without re-exporting the image.

    Covers entries written before a field existed (e.g. `organisation`,
    `attribution`) and any later yaml edits. Leaves image-derived fields
    (`source_file`, `source_dimensions`, `processed_at`, `exports`) intact.
    Silently no-ops if the file is missing — nothing to refresh.
    """
    meta_path = mirror_path(out_dir / "metadata.json")
    if not meta_path.exists():
        return
    try:
        current = json.loads(meta_path.read_text())
    except (OSError, json.JSONDecodeError):
        log.warning("Failed to read existing metadata at %s", meta_path)
        return

    attribution = entry.get("attribution") or _scraped_attribution(src_file_name)
    desired = {
        "id": entry["body"],
        "source": entry["source"],
        "organisation": entry["organisation"],
        "attribution": attribution,
        "description": entry.get("description"),
        "type": entry["type"],
    }
    if all(current.get(k) == v for k, v in desired.items()):
        return
    current.update(desired)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(current, indent=2))
    log.info("refreshed metadata from yaml: %s/metadata.json", out_dir.name)


def _scraped_attribution(src_file_name: str) -> str | None:
    """Look up `attribution_guess` from the per-texture scraped source metadata.

    The `texture_sources` downloader writes one JSON per raw texture file
    (keyed by file stem) to `source_metadata/parsed/`. Returns None when no
    scrape exists for this file or the scrape has no attribution.
    """
    parsed = SOURCE_METADATA_PARSED_DIR / f"{Path(src_file_name).stem}.json"
    if not parsed.exists():
        return None
    try:
        data = json.loads(parsed.read_text())
    except (OSError, json.JSONDecodeError):
        log.warning("Failed to read scraped source metadata at %s", parsed)
        return None
    guess = data.get("attribution_guess")
    return guess if isinstance(guess, str) and guess.strip() else None


def _tier_for_size(size: int) -> str:
    for dim, tier, _ in SIZE_TARGETS:
        if size <= dim:
            return tier
    return "high"


def _size_target(export_dim: int) -> int | None:
    for dim, _, target in SIZE_TARGETS:
        if export_dim <= dim:
            return target
    return None


def _resize(img: Image.Image, max_dim: int) -> Image.Image:
    w, h = img.size
    scale = max_dim / max(w, h)
    return img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)


def _save_webp(
    img: Image.Image, path: Path, lossless: bool, max_bytes: int | None = MAX_FILE_BYTES
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
        img.save(path, "webp", **_webp_kwargs(lossless))
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
        if quality > MIN_QUALITY:
            quality -= 10
            continue
        # Hit the quality floor; shrink by SHRINK_RATIO and retry at q=80.
        new_dim = int(max(current.size) * SHRINK_RATIO)
        if new_dim < MIN_DIM_AFTER_SHRINK:
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
        current = _resize(current, new_dim)
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


_IMAGE_EXTS = {".tif", ".tiff", ".png", ".jpg", ".jpeg"}

# Matches an export file from the cloud bundle: `{tier}_{YYYYMMDDHH}.webp`.
# Used to identify outputs whose source snapshot has vanished from disk so
# the bundle doesn't accumulate ghost frames on subsequent runs.
_CLOUD_OUTPUT_RE = re.compile(r"^([a-z]+)_(\d{10})\.webp$")


def _cloud_frame_id(path: Path) -> str | None:
    """Derive a sortable frame id from a date-partitioned snapshot path.

    ``yyyy/mm/dd/HH.png`` → ``YYYYMMDDHH``. Returns None if the path
    doesn't fit that layout (so the caller can warn instead of silently
    grouping unrelated snapshots).
    """
    try:
        rel = path.relative_to(EARTH_CLOUDS_DIR).with_suffix("")
    except ValueError:
        return None
    parts = rel.parts
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        return None
    yyyy, mm, dd, hh = parts
    return f"{yyyy}{mm}{dd}{hh}"


def _expand_entry_files(entry: dict) -> list[str]:
    """Resolve an entry's ``file`` field into the concrete raw filenames it covers.

    Single-frame entries return ``[entry["file"]]``. ``cylindrical_monthly``
    entries python-format ``{month:02d}`` (and the unpadded ``{month}``) for
    ``range(1, months+1)``.
    """
    if entry.get("type") == "cylindrical_monthly":
        months = entry.get("months", 12)
        return [entry["file"].format(month=m) for m in range(1, months + 1)]
    return [entry["file"]]


def _stale_metadata_reason(existing: dict, entry: dict) -> str | None:
    """Return a reason string if on-disk metadata is structurally stale.

    Used by ``_try_skip`` to force a reprocess when a monthly entry's
    shape (frame count / template) has diverged from the last export.
    Returns None for single-frame entries — their skip is driven by
    file existence and the per-export size cap. Cloud overlays don't
    flow through ``_try_skip`` (own snapshot-set comparison), so they
    aren't handled here.
    """
    type_ = entry.get("type")
    if type_ in ("cylindrical", "cylindrical_monthly", "cylindrical_specular"):
        cur_align = existing.get("alignment") or _DEFAULT_ALIGNMENT
        if cur_align != _alignment(entry):
            return "alignment changed"
    if type_ == "cylindrical_monthly":
        if (
            existing.get("type") != type_
            or existing.get("frames") != entry.get("months", 12)
            or existing.get("source_file") != entry["file"]
        ):
            return "yaml entry shape changed"
    if type_ == "cubemap_skybox":
        if (
            existing.get("type") != type_
            or tuple(existing.get("faces") or ()) != SKYBOX_FACES
            or existing.get("tier_face_size") != SKYBOX_TIER_SIZES
        ):
            return "skybox entry shape changed"
    return None


def _any_export_over_cap(out_dir: Path) -> bool:
    """True if any export recorded in metadata.json exceeds MAX_FILE_BYTES.

    Used to auto-reprocess stale bundles after the cap is tightened or a
    deploy fails upload. Walks the ``exports`` tree so it works on both the
    flat (``{tier: rec}``) and frame-nested (``{frame: {tier: rec}}``) shapes.
    Safe against corrupt/missing metadata: returns False (falls through to
    the normal skip path, which will write a fresh metadata via
    ``_refresh_metadata_from_yaml`` if needed).
    """
    meta_path = mirror_path(out_dir / "metadata.json")
    if not meta_path.exists():
        return False
    try:
        meta = json.loads(meta_path.read_text())
    except (OSError, json.JSONDecodeError):
        return False

    class _MaybeSized(TypedDict, total=False):
        size_bytes: int

    def _walk(node: Any) -> bool:
        if not isinstance(node, dict):
            return False
        entry = cast("_MaybeSized", node)
        size = entry.get("size_bytes")
        if size is not None:
            return size > MAX_FILE_BYTES
        return any(_walk(v) for v in node.values())

    return _walk(meta.get("exports") or {})


class TextureProcessor:
    def __init__(self) -> None:
        main_yaml = DOWNLOAD_DIR / "textures" / "download-metadata.yaml"
        bodies: list[dict] = yaml.safe_load(main_yaml.read_text())["bodies"]
        for entry in bodies:
            entry["_source_dir"] = RAW_DIR

        # Each misc/<asset>/ may carry its own download-metadata.yaml with the
        # same schema; entries get stamped with `_source_dir` pointing at the
        # subdir so the processor finds the file without a global `raw/` move.
        if MISC_DIR.is_dir():
            for sub in sorted(MISC_DIR.iterdir()):
                if not sub.is_dir():
                    continue
                sub_yaml = sub / "download-metadata.yaml"
                if not sub_yaml.is_file():
                    continue
                data = yaml.safe_load(sub_yaml.read_text()) or {}
                for entry in data.get("bodies") or []:
                    entry["_source_dir"] = sub
                    bodies.append(entry)

        self._raw_meta: list[dict] = bodies
        self._global_warnings: list[str] = []

    def _reset_texture_available(self) -> None:
        session = get_session()
        session.query(Object).update({Object.map_texture_available: False})
        session.commit()

    def _mark_texture_available(self, object_id: str) -> None:
        session = get_session()
        session.query(Object).filter(Object.id == object_id).update(
            {Object.map_texture_available: True}
        )
        session.commit()

    def _export(
        self,
        img: Image.Image,
        object_id: str,
        out_dir: Path,
        filename_suffix: str = "",
    ) -> tuple[dict[str, dict], list[str]]:
        """Export image at applicable sizes; promotes largest to lossless high if source is below the high tier.

        ``filename_suffix`` is appended to each tier name in the on-disk file
        (e.g. ``"_01"`` → ``low_01.webp``); the returned dict is still keyed
        by bare tier name so callers can nest under a frame key.
        """
        w, h = img.size
        capped = min(max(w, h), WEBP_MAX)
        # Sizes to export: all EXPORT_SIZES that fit below the cap, plus the cap itself
        sizes = [s for s in EXPORT_SIZES if s < capped]
        sizes.append(capped)

        exports: dict[str, dict] = {}
        warnings: list[str] = []

        for size in sizes:
            tier = _tier_for_size(size)
            resized = _resize(img, size)
            rec = _save_webp(
                resized, out_dir / f"{tier}{filename_suffix}.webp", lossless=False
            )
            exports[tier] = rec

            target = _size_target(size)
            if target and rec["size_bytes"] > target:
                msg = f"{object_id}/{tier}{filename_suffix}.webp: {rec['size_bytes'] / 1024:.0f} KiB exceeds {target // 1024} KiB target"
                log.warning(msg)
                warnings.append(msg)

        # If no high was produced (source ≤ 8192), promote the largest export to high
        # as a lossless copy — but only if it's small enough to be worth it
        if "high" not in exports:
            largest_rec = exports[max(exports, key=lambda t: exports[t]["width"])]
            if largest_rec["size_bytes"] < 300 * 1024:
                exports["high"] = _save_webp(
                    _resize(img, largest_rec["width"]),
                    out_dir / f"high{filename_suffix}.webp",
                    lossless=True,
                )

        return exports, warnings

    def _try_skip(
        self,
        out_dir: Path,
        entry: dict,
        *,
        attribution_file: str,
        label: str,
    ) -> bool:
        """Refresh yaml fields and return True if processing can be skipped.

        Returns False when metadata is missing, the entry's shape has
        diverged from the on-disk metadata (monthly frame-count/template
        change, or a fresher clouds snapshot on disk), or any export
        exceeds the file cap. In all other cases yaml-sourced fields are
        patched into the existing metadata.json and the texture is marked
        available.
        """
        meta_path = mirror_path(out_dir / "metadata.json")
        if not meta_path.exists():
            return False

        try:
            existing = json.loads(meta_path.read_text())
        except (OSError, json.JSONDecodeError):
            existing = {}

        reason = _stale_metadata_reason(existing, entry)
        if reason:
            log.info("reprocessing %s: %s", label, reason)
            return False

        if _any_export_over_cap(out_dir):
            log.info(
                "reprocessing %s: existing export(s) exceed %.1f MiB cap",
                label,
                MAX_FILE_BYTES / 1024 / 1024,
            )
            return False

        log.debug("skipping %s (already processed, use force=True to reprocess)", label)
        _refresh_metadata_from_yaml(out_dir, entry, attribution_file)
        self._mark_texture_available(entry["body"])
        return True

    def _write_metadata(
        self,
        out_dir: Path,
        entry: dict,
        *,
        source_file: str,
        attribution_file: str,
        source_dims: list[int] | None,
        exports: dict,
        extra_fields: dict | None = None,
    ) -> None:
        """Build and write metadata.json; mark the texture available.

        ``source_file`` is what gets recorded in metadata (the literal raw
        filename or the monthly template); ``attribution_file`` is the
        concrete filename used to look up scraped attribution (the first
        frame for monthly entries).
        """
        self._mark_texture_available(entry["body"])
        attribution = entry.get("attribution") or _scraped_attribution(attribution_file)
        metadata: dict = {
            "id": entry["body"],
            "source": entry["source"],
            "organisation": entry["organisation"],
            "attribution": attribution,
            "description": entry.get("description"),
            "type": entry["type"],
            **(extra_fields or {}),
            "source_file": source_file,
            "source_dimensions": source_dims,
            "processed_at": datetime.now(UTC).isoformat(),
            "exports": exports,
        }
        meta_path = mirror_path(out_dir / "metadata.json")
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(metadata, indent=2))

    def process_all(self, force: bool = False) -> None:
        """Process all textures listed in download-metadata.yaml.

        Warns about any image files in RAW_DIR not referenced by the metadata.
        Writes a global warnings file to the textures download directory.
        """
        self._global_warnings = []
        self._reset_texture_available()
        # `known_files` only gates the RAW_DIR untracked-files check below, so
        # we restrict it to entries actually sourced from raw/. misc/ entries
        # have their own per-subdir manifests and aren't expected in raw/.
        known_files: set[str] = set()
        for entry in self._raw_meta:
            if entry.get("_source_dir", RAW_DIR) == RAW_DIR:
                known_files.update(_expand_entry_files(entry))

        for entry in self._raw_meta:
            if entry.get("skip"):
                continue
            if entry.get("type") == "cylindrical_monthly":
                self._process_monthly(entry, force=force)
                continue
            if entry.get("type") == "cylindrical_specular":
                self._process_specular(entry, force=force)
                continue
            if entry.get("type") == "cubemap_skybox":
                self._process_skybox(entry, force=force)
                continue
            src = entry.get("_source_dir", RAW_DIR) / entry["file"]
            if not src.exists():
                msg = f"listed in metadata but not found: {entry['file']}"
                log.warning(msg)
                self._global_warnings.append(msg)
                continue
            self.process(src, force=force)

        self._process_clouds(force=force)

        for f in sorted(RAW_DIR.iterdir()):
            if f.suffix.lower() in _IMAGE_EXTS and f.name not in known_files:
                msg = f"untracked file not in download-metadata.yaml: {f.name}"
                log.warning(msg)
                self._global_warnings.append(msg)

        warnings_file = RAW_DIR.parent / "warnings.json"
        warnings_file.write_text(json.dumps(self._global_warnings, indent=2))
        if self._global_warnings:
            log.warning(
                "%d global texture warning(s) — see %s",
                len(self._global_warnings),
                warnings_file,
            )

    def process(self, src: Path | str, force: bool = False) -> Path:
        """Process a raw texture into WebP exports.

        Reads body info from raw/download-metadata.yaml.
        Exports are written to PROCESSED_DIR/<object_id>/ alongside a metadata.json.
        Returns the output directory.
        """
        src = Path(src)
        entry = next((b for b in self._raw_meta if b["file"] == src.name), None)
        if entry is None:
            msg = f"{src.name} not found in download-metadata.yaml"
            log.warning(msg)
            self._global_warnings.append(msg)
            return PROCESSED_DIR
        if entry.get("skip"):
            log.debug("skipping %s (marked skip in download-metadata.yaml)", src.name)
            return PROCESSED_DIR

        object_id = entry["body"]
        out_dir = PROCESSED_DIR / object_id

        if not force and self._try_skip(
            out_dir, entry, attribution_file=src.name, label=src.name
        ):
            return out_dir

        out_dir.mkdir(parents=True, exist_ok=True)
        img = _open_image(src)
        source_dims = [img.width, img.height]
        img = _align_cylindrical(img, **_alignment(entry))
        exports, warnings = self._export(img, object_id, out_dir)
        self._global_warnings.extend(warnings)

        self._write_metadata(
            out_dir,
            entry,
            source_file=src.name,
            attribution_file=src.name,
            source_dims=source_dims,
            exports=exports,
            extra_fields={"alignment": _alignment(entry)},
        )
        log.info("processed %s → %s (%d exports)", src.name, object_id, len(exports))
        return out_dir

    def _process_specular(self, entry: dict, force: bool = False) -> Path:
        """Process a `cylindrical_specular` entry from a bathymetry source.

        Output goes to ``{body}_specular/`` — a sibling of the surface texture
        and ``_clouds`` bundle. The exported WebP is a single-channel ocean
        mask (land=0, ocean=255); the renderer routes it into whichever
        material slot (roughness, specular intensity) it sees fit.
        """
        src = entry.get("_source_dir", RAW_DIR) / entry["file"]
        if not src.exists():
            msg = f"specular source missing: {entry['file']}"
            log.warning(msg)
            self._global_warnings.append(msg)
            return PROCESSED_DIR

        object_id = f"{entry['body']}{SPECULAR_SUFFIX}"
        out_dir = PROCESSED_DIR / object_id

        # Helpers (`_try_skip`, `_write_metadata`, `_mark_texture_available`)
        # all key off entry["body"]. Override it to the suffixed export id so
        # the on-disk metadata.json's `id` matches the directory — same
        # convention `_process_clouds` uses for `naif-399_clouds`. The DB
        # update for `naif-399_specular` is a harmless no-op (no such row).
        entry = {**entry, "body": object_id}

        if not force and self._try_skip(
            out_dir, entry, attribution_file=src.name, label=object_id
        ):
            return out_dir

        out_dir.mkdir(parents=True, exist_ok=True)
        img = _open_specular_source(src)
        source_dims = [img.width, img.height]
        img = _align_cylindrical(img, **_alignment(entry))
        exports, warnings = self._export(img, object_id, out_dir)
        self._global_warnings.extend(warnings)

        self._write_metadata(
            out_dir,
            entry,
            source_file=src.name,
            attribution_file=src.name,
            source_dims=source_dims,
            exports=exports,
            extra_fields={"alignment": _alignment(entry)},
        )
        log.info(
            "processed specular %s → %s (%d exports)", src.name, object_id, len(exports)
        )
        return out_dir

    def _process_skybox(self, entry: dict, force: bool = False) -> Path:
        """Process a ``cubemap_skybox`` entry from an HDR equirectangular EXR.

        Loads the source EXR linear-light, applies an exposure-bumped Reinhard
        tonemap, projects to six cubemap faces (px, nx, py, ny, pz, nz) at
        each tier size, and writes one lossy WebP per face per tier:
        ``{tier}_{face}.webp`` under ``PROCESSED_DIR/<body>/``. A single
        metadata.json records the face list, tier sizes, and per-file size
        records (nested ``{tier: {face: rec}}``).

        Skip semantics mirror the other processors: ``_try_skip`` short-
        circuits when metadata exists, the entry shape is unchanged, and no
        export exceeds the size cap.
        """
        src = entry.get("_source_dir", RAW_DIR) / entry["file"]
        if not src.exists():
            msg = f"skybox source missing: {entry['file']}"
            log.warning(msg)
            self._global_warnings.append(msg)
            return PROCESSED_DIR

        object_id = entry["body"]
        out_dir = PROCESSED_DIR / object_id

        if not force and self._try_skip(
            out_dir, entry, attribution_file=src.name, label=f"{object_id} skybox"
        ):
            return out_dir

        # Pre-flight: the streaming loader downsamples to ~384 MiB and
        # py360convert's 4K-per-face cubemap working set adds another ~1 GiB;
        # 2 GiB available is comfortable headroom. (The earlier whole-image
        # imageio load needed 30+ GiB and would OOM-kill the process.)
        SKYBOX_MIN_AVAILABLE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB
        avail = _mem_available_bytes()
        if avail is not None and avail < SKYBOX_MIN_AVAILABLE_BYTES:
            msg = (
                f"skybox {object_id}: insufficient memory "
                f"({avail / 1024**3:.1f} GiB available, need ≥{SKYBOX_MIN_AVAILABLE_BYTES / 1024**3:.0f} GiB); "
                f"close other apps and rerun"
            )
            log.error(msg)
            self._global_warnings.append(msg)
            return PROCESSED_DIR

        out_dir.mkdir(parents=True, exist_ok=True)

        log.info("loading + tonemapping skybox EXR %s (streaming)…", src.name)
        ldr_equirect = _load_and_tonemap_skybox_streaming(src)
        h, w, _ = ldr_equirect.shape
        # Source dims for metadata are the *original* EXR dimensions, not the
        # downsampled working buffer — record both via the explicit factor.
        src_w = w * _SKYBOX_DOWNSAMPLE
        src_h = h * _SKYBOX_DOWNSAMPLE
        gc.collect()

        exports: dict[str, dict[str, dict]] = {}
        warnings: list[str] = []
        high_size = SKYBOX_TIER_SIZES["high"]
        log.info("extracting cubemap faces at %dpx (high tier)…", high_size)
        # Single e2c pass at high tier; downsample for lower tiers below.
        raw_faces = py360convert.e2c(
            ldr_equirect, face_w=high_size, mode="bilinear", cube_format="dict"
        )
        # Remap py360convert's F/R/B/L/U/D keys to WebGL axis labels.
        high_faces = {_PY360_TO_FACE[k]: v for k, v in raw_faces.items()}
        del ldr_equirect, raw_faces
        gc.collect()

        for tier, face_size in SKYBOX_TIER_SIZES.items():
            tier_exports: dict[str, dict] = {}
            for face in SKYBOX_FACES:
                img = Image.fromarray(high_faces[face], mode="RGB")
                if face_size != high_size:
                    img = img.resize((face_size, face_size), Image.Resampling.LANCZOS)
                rec = _save_webp(img, out_dir / f"{tier}_{face}.webp", lossless=False)
                tier_exports[face] = rec

                target = _size_target(face_size)
                if target and rec["size_bytes"] > target:
                    msg = (
                        f"{object_id}/{tier}_{face}.webp: "
                        f"{rec['size_bytes'] / 1024:.0f} KiB exceeds {target // 1024} KiB target"
                    )
                    log.warning(msg)
                    warnings.append(msg)
            exports[tier] = tier_exports
        del high_faces
        gc.collect()
        self._global_warnings.extend(warnings)

        self._write_metadata(
            out_dir,
            entry,
            source_file=src.name,
            attribution_file=src.name,
            source_dims=[src_w, src_h],
            exports=exports,
            extra_fields={
                "encoding": "webp",
                "frame": "j2000",
                "faces": list(SKYBOX_FACES),
                "tiers": list(SKYBOX_TIER_SIZES),
                "tier_face_size": dict(SKYBOX_TIER_SIZES),
                "exposure": SKYBOX_EXPOSURE,
                "working_equirect_size": [w, h],
                "downsample_from_source": _SKYBOX_DOWNSAMPLE,
            },
        )
        log.info(
            "processed skybox %s → %s (%d faces × %d tiers)",
            src.name,
            object_id,
            len(SKYBOX_FACES),
            len(SKYBOX_TIER_SIZES),
        )
        return out_dir

    def _process_monthly(self, entry: dict, force: bool = False) -> Path:
        """Process a ``cylindrical_monthly`` entry: one body, ``months`` frames.

        Each frame's tier files land as ``{tier}_{NN}.webp`` in the body's
        directory; one ``metadata.json`` records all of them with ``exports``
        keyed by zero-padded month string.

        Skip semantics mirror ``process()``: if metadata exists and no export
        exceeds the file cap, the image work is skipped and only the
        yaml-sourced fields are refreshed. Use ``force=True`` to redo the
        webp encoding (e.g. after changing tier sizes).
        """
        object_id = entry["body"]
        out_dir = PROCESSED_DIR / object_id
        months = entry.get("months", 12)
        file_template = entry["file"]
        expected_files = _expand_entry_files(entry)
        source_dir: Path = entry.get("_source_dir", RAW_DIR)

        missing = [f for f in expected_files if not (source_dir / f).exists()]
        if missing:
            for f in missing:
                msg = f"monthly source missing: {f}"
                log.warning(msg)
                self._global_warnings.append(msg)
            if len(missing) == months:
                # Nothing to process at all; bail before touching out_dir.
                return PROCESSED_DIR

        if not force and self._try_skip(
            out_dir,
            entry,
            attribution_file=expected_files[0],
            label=f"{object_id} monthly",
        ):
            return out_dir

        out_dir.mkdir(parents=True, exist_ok=True)

        # Strip prior flat-layout outputs (low/medium/high.webp) when migrating
        # a body from a single-frame entry to a monthly one. Leaving them
        # around would ship stale assets the renderer might pick up.
        for stale in ("low.webp", "medium.webp", "high.webp"):
            stale_path = out_dir / stale
            if stale_path.exists():
                stale_path.unlink()
                log.info("removed stale single-frame export %s", stale_path.name)

        all_exports: dict[str, dict[str, dict]] = {}
        source_dims: list[int] | None = None

        align = _alignment(entry)
        for m in range(1, months + 1):
            fname = file_template.format(month=m)
            src = source_dir / fname
            if not src.exists():
                continue
            img = _open_image(src)
            if source_dims is None:
                source_dims = [img.width, img.height]
            img = _align_cylindrical(img, **align)
            suffix = f"_{m:02d}"
            exports, warnings = self._export(img, object_id, out_dir, suffix)
            all_exports[f"{m:02d}"] = exports
            self._global_warnings.extend(warnings)

        if not all_exports:
            # Every source was missing — we logged per-file warnings above.
            return out_dir

        tier_count = len(next(iter(all_exports.values())))
        self._write_metadata(
            out_dir,
            entry,
            source_file=file_template,
            attribution_file=expected_files[0],
            source_dims=source_dims,
            exports=all_exports,
            extra_fields={"frames": months, "alignment": align},
        )
        log.info(
            "processed %s → %s monthly (%d frames × %d tiers)",
            file_template,
            object_id,
            len(all_exports),
            tier_count,
        )
        return out_dir

    def _process_clouds(self, force: bool = False) -> Path:
        """Process every Earth cloud-cover snapshot into per-frame WebP exports.

        Walks every PNG under ``EARTH_CLOUDS_DIR`` (date tree written by the
        earth_clouds downloader at 3h cadence), derives a sortable
        ``YYYYMMDDHH`` frame id from each path, and exports as
        ``{tier}_{frame_id}.webp`` alongside the Earth surface texture. A
        single top-level metadata.json carries the union of frames; per-frame
        ``size_bytes`` / ``source_file`` are intentionally omitted — they'd
        just repeat across thousands of snapshots.

        Skip semantics: if the existing metadata's ``frames`` list matches
        the on-disk PNG inventory, the image work is a no-op. Otherwise,
        only frames whose low-tier output is missing are re-encoded and
        outputs for vanished snapshots are deleted. ``force=True``
        re-encodes every frame.
        """
        if not EARTH_CLOUDS_DIR.exists():
            log.debug("clouds: %s does not exist, skipping", EARTH_CLOUDS_DIR)
            return PROCESSED_DIR

        pngs = sorted(EARTH_CLOUDS_DIR.rglob("*.png"))
        if not pngs:
            msg = f"no earth_clouds snapshots in {EARTH_CLOUDS_DIR}"
            log.warning(msg)
            self._global_warnings.append(msg)
            return PROCESSED_DIR

        inputs: list[tuple[str, Path]] = []
        seen: set[str] = set()
        for p in pngs:
            fid = _cloud_frame_id(p)
            if fid is None:
                msg = f"cloud snapshot at unexpected path: {p.relative_to(EARTH_CLOUDS_DIR).as_posix()}"
                log.warning(msg)
                self._global_warnings.append(msg)
                continue
            if fid in seen:
                continue
            seen.add(fid)
            inputs.append((fid, p))
        target_frames = [fid for fid, _ in inputs]

        out_dir = PROCESSED_DIR / EARTH_CLOUDS_OBJECT_ID
        meta_path = mirror_path(out_dir / "metadata.json")

        download_meta_path = EARTH_CLOUDS_DIR / "metadata.json"
        download_meta: dict = {}
        if download_meta_path.exists():
            try:
                download_meta = json.loads(download_meta_path.read_text())
            except (OSError, json.JSONDecodeError):
                log.warning(
                    "failed to read earth_clouds metadata at %s", download_meta_path
                )

        if not force and meta_path.exists():
            try:
                existing = json.loads(meta_path.read_text())
            except (OSError, json.JSONDecodeError):
                existing = {}
            if existing.get("frames") == target_frames:
                log.debug(
                    "skipping clouds (already processed %d frames, use force=True to reprocess)",
                    len(target_frames),
                )
                self._mark_texture_available(EARTH_CLOUDS_OBJECT_ID)
                return out_dir

        out_dir.mkdir(parents=True, exist_ok=True)

        # Drop outputs for frames the downloader no longer has on disk so
        # the bundle doesn't accumulate ghost snapshots.
        target_set = set(target_frames)
        for f in out_dir.glob("*.webp"):
            m = _CLOUD_OUTPUT_RE.match(f.name)
            if not m:
                continue
            if m.group(2) not in target_set:
                f.unlink()
                log.info("removed stale cloud frame %s", f.name)

        tiers: list[str] = []
        for fid, src in inputs:
            suffix = f"_{fid}"
            if not force and (out_dir / f"low{suffix}.webp").exists():
                # Existing output covers this frame; tier discovery falls to
                # any frame we actually encode (they share dims, so tiers
                # match), or the post-loop fallback below.
                continue
            img = _open_image(src)
            exports, warnings = self._export(
                img, EARTH_CLOUDS_OBJECT_ID, out_dir, suffix
            )
            self._global_warnings.extend(warnings)
            if not tiers:
                tiers = sorted(exports.keys())

        # Every frame was already on disk — recover the tier list from one
        # of the existing outputs so the metadata stays accurate.
        if not tiers and target_frames:
            first_fid = target_frames[0]
            tiers = sorted(
                t
                for t in ("low", "medium", "high")
                if (out_dir / f"{t}_{first_fid}.webp").exists()
            )

        self._mark_texture_available(EARTH_CLOUDS_OBJECT_ID)
        metadata: dict = {
            "id": EARTH_CLOUDS_OBJECT_ID,
            "source": download_meta.get("source_url", ""),
            "organisation": "EUMETSAT",
            "attribution": download_meta.get("attribution"),
            "description": "Near-real-time cloud-cover overlay (3-hour cadence).",
            "type": "clouds_overlay",
            "tiers": tiers,
            "frames": target_frames,
            "processed_at": datetime.now(UTC).isoformat(),
        }
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(metadata, indent=2))
        log.info(
            "processed clouds → %s (%d frames × %d tiers)",
            EARTH_CLOUDS_OBJECT_ID,
            len(target_frames),
            len(tiers),
        )
        return out_dir


def to_webp_tiled(
    src: Path | str, lossless: bool = False, max_size: int = WEBP_MAX
) -> list[Path]:
    """Split image into uniform tiles and save each as WebP.

    Returns the list of saved paths (single item if no tiling needed).
    """
    src = Path(src)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    img = _open_image(src)
    w, h = img.size

    cols = math.ceil(w / max_size)
    rows = math.ceil(h / max_size)
    tile_w = math.ceil(w / cols)
    tile_h = math.ceil(h / rows)

    saved = []
    for row in range(rows):
        for col in range(cols):
            x0, y0 = col * tile_w, row * tile_h
            tile = img.crop((x0, y0, min(x0 + tile_w, w), min(y0 + tile_h, h)))
            name = (
                f"{src.stem}.webp"
                if rows == cols == 1
                else f"{src.stem}_r{row}_c{col}.webp"
            )
            out = PROCESSED_DIR / name
            tile.save(out, "webp", **_webp_kwargs(lossless))
            saved.append(out)
            log.debug("saved %s (%dx%d)", out.name, tile.width, tile.height)

    return saved


def to_webp_resized(
    src: Path | str, lossless: bool = False, max_size: int = WEBP_MAX
) -> Path:
    """Downscale image to fit within WebP limits if needed and save as WebP.

    Returns the saved path.
    """
    src = Path(src)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    img = _open_image(src)
    w, h = img.size

    if w > max_size or h > max_size:
        img = _resize(img, max_size)
        log.warning(
            "%s exceeded WebP limit (%dx%d), resized to %dx%d",
            src.name,
            w,
            h,
            img.width,
            img.height,
        )

    out = PROCESSED_DIR / f"{src.stem}.webp"
    img.save(out, "webp", **_webp_kwargs(lossless))
    log.debug("saved %s (%dx%d)", out.name, img.width, img.height)
    return out
