import json
import logging
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import tifffile
import yaml
from PIL import Image

from space_map_data.utils.paths import DOWNLOAD_DIR

Image.MAX_IMAGE_PIXELS = None

log = logging.getLogger(__name__)

RAW_DIR = DOWNLOAD_DIR / "textures" / "raw"
PROCESSED_DIR = DOWNLOAD_DIR / "textures" / "processed"
WEBP_MAX = 16383  # WebP hard limit per dimension

# Images below this dimension get lossless + lossy only (no multi-size exports)
SMALL_DIM = 2048

# Power-of-2 export sizes for large images
EXPORT_SIZES = [2048, 8192]

# File size targets per tier (upper-bound lookup: applies to exports <= the key)
SIZE_TARGETS = [
    (2048, 300 * 1024),  # small tier: 300 KiB
    (8192, 2 * 1024 * 1024),  # medium tier: 2 MiB
    (WEBP_MAX, 6 * 1024 * 1024),  # high tier: 6 MiB
]


_NODATA_THRESHOLD = -1e31  # GDAL nodata for float TIFFs is -1e+32


def _linear_to_srgb(x: np.ndarray) -> np.ndarray:
    """Peicewise sRGB EOTF — linear toe + power curve."""
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def _open_image(path: Path) -> Image.Image:
    try:
        return Image.open(path)
    except Exception:
        pass

    arr = tifffile.imread(str(path))
    if arr.dtype.kind != "f":
        raise ValueError(f"tifffile loaded {path.name} as {arr.dtype}, expected float")

    nodata_mask = arr < _NODATA_THRESHOLD
    arr = np.clip(arr, 0.0, None)
    arr[nodata_mask] = 0.0
    arr = arr.astype(np.float32)

    # Joint stretch: single (lo, hi) across all channels preserves color ratios
    valid_mask = ~nodata_mask.any(axis=-1)  # pixels valid in ALL channels
    valid_px = arr[valid_mask]  # shape (N, 3)
    lo = np.percentile(valid_px, 2) if valid_px.size else 0.0
    hi = np.percentile(valid_px, 98) if valid_px.size else 1.0
    arr = np.clip((arr - lo) / max(hi - lo, 1e-6), 0.0, 1.0)

    # sRGB transfer function (not a simple gamma power)
    arr = _linear_to_srgb(arr)

    arr = (arr * 255.0).astype(np.uint8)
    return Image.fromarray(arr, mode="RGB")


def _webp_kwargs(lossless: bool) -> dict:
    return {"lossless": True, "method": 6} if lossless else {"quality": 80}


def _size_target(export_dim: int) -> int | None:
    for dim, target in SIZE_TARGETS:
        if export_dim <= dim:
            return target
    return None


def _resize(img: Image.Image, max_dim: int) -> Image.Image:
    w, h = img.size
    scale = max_dim / max(w, h)
    return img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)


def _save_webp(img: Image.Image, path: Path, lossless: bool) -> dict:
    img.save(path, "webp", **_webp_kwargs(lossless))
    size = path.stat().st_size
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


class TextureProcessor:
    def __init__(self) -> None:
        self._raw_meta: list[dict] = yaml.safe_load(
            (RAW_DIR / "download-metadata.yaml").read_text()
        )["bodies"]

    def _load_entry(self, filename: str, warnings: list[str]) -> dict | None:
        entry = next((b for b in self._raw_meta if b["file"] == filename), None)
        if entry is None:
            msg = f"{filename} not found in download-metadata.yaml"
            log.warning(msg)
            warnings.append(msg)
            return None
        if entry.get("skip"):
            log.debug("skipping %s (marked skip in download-metadata.yaml)", filename)
            return None
        return entry

    def _export_small(
        self, img: Image.Image, prefix: str, out_dir: Path
    ) -> tuple[list[dict], list[str]]:
        exports = []
        for lossless in (False, True):
            suffix = "lossless" if lossless else "q80"
            exports.append(
                _save_webp(img, out_dir / f"{prefix}_{suffix}.webp", lossless)
            )
        return exports, []

    def _export_large(
        self, img: Image.Image, prefix: str, out_dir: Path
    ) -> tuple[list[dict], list[str]]:
        w, h = img.size
        capped = min(max(w, h), WEBP_MAX)
        sizes = [s for s in EXPORT_SIZES if s < capped]
        sizes.append(capped)

        exports = []
        warnings = []

        for size in sizes:
            resized = _resize(img, size)
            rec = _save_webp(resized, out_dir / f"{prefix}_{size}.webp", lossless=False)
            exports.append(rec)

            target = _size_target(size)
            if target and rec["size_bytes"] > target:
                msg = f"{rec['file']}: {rec['size_bytes'] / 1024:.0f} KiB exceeds {target // 1024} KiB target"
                log.warning(msg)
                warnings.append(msg)

        # If the largest export is under 300 KiB, also save lossless at that size
        if exports[-1]["size_bytes"] < 300 * 1024:
            rec = _save_webp(
                _resize(img, sizes[-1]),
                out_dir / f"{prefix}_{sizes[-1]}_lossless.webp",
                lossless=True,
            )
            exports.append(rec)

        return exports, warnings

    def process(self, src: Path | str, force: bool = False) -> Path:
        """Process a raw texture into WebP exports.

        Reads body info from raw/download-metadata.yaml.
        Exports are written to processed/<body>/ alongside a metadata.json.
        Returns the output directory.
        """
        src = Path(src)
        warnings: list[str] = []
        entry = self._load_entry(src.name, warnings)
        if entry is None:
            return PROCESSED_DIR

        body = entry["body"]
        out_dir = PROCESSED_DIR / body

        if not force and (out_dir / "metadata.json").exists():
            log.debug(
                "skipping %s (already processed, use force=True to reprocess)", src.name
            )
            return out_dir

        out_dir.mkdir(parents=True, exist_ok=True)

        img = _open_image(src)
        w, h = img.size
        prefix = f"{body}"

        if max(w, h) < SMALL_DIM:
            exports, warnings = self._export_small(img, prefix, out_dir)
        else:
            exports, warnings = self._export_large(img, prefix, out_dir)

        metadata = {
            "body": body,
            "source": entry["source"],
            "description": entry.get("description"),
            "type": entry["type"],
            "source_file": src.name,
            "source_dimensions": [w, h],
            "processed_at": datetime.now(UTC).isoformat(),
            "exports": exports,
            "warnings": warnings,
        }

        (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))
        log.info(
            "processed %s → %d exports, %d warnings",
            src.name,
            len(exports),
            len(warnings),
        )

        return out_dir


# --- Low-level helpers (kept for ad-hoc use) ---


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
        scale = max_size / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
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
