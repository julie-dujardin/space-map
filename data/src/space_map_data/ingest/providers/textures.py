import json
import logging
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import tifffile
import yaml
from PIL import Image

from space_map_data.models.object import Object
from space_map_data.utils.db import get_session
from space_map_data.utils.paths import DOWNLOAD_DIR, EXPORT_DIR

Image.MAX_IMAGE_PIXELS = None

log = logging.getLogger(__name__)

RAW_DIR = DOWNLOAD_DIR / "textures" / "raw"
PROCESSED_DIR = EXPORT_DIR / "v1" / "textures"
WEBP_MAX = 16383  # WebP hard limit per dimension
EXPORT_SIZES = [2048, 8192]  # intermediate sizes to generate for large images

# Upper-bound lookup: (max_dim, tier_name, size_target)
SIZE_TARGETS = [
    (2048, "low", 300 * 1024),
    (8192, "medium", 2 * 1024 * 1024),
    (WEBP_MAX, "high", 6 * 1024 * 1024),
]


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


def _webp_kwargs(lossless: bool) -> dict:
    return {"lossless": True, "method": 6} if lossless else {"quality": 80}


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


_IMAGE_EXTS = {".tif", ".tiff", ".png", ".jpg", ".jpeg"}


class TextureProcessor:
    def __init__(self) -> None:
        self._raw_meta: list[dict] = yaml.safe_load(
            (RAW_DIR / "download-metadata.yaml").read_text()
        )["bodies"]
        self._global_warnings: list[str] = []

    def _mark_texture_available(self, object_id: str) -> None:
        session = get_session()
        session.query(Object).filter(Object.id == object_id).update(
            {Object.map_texture_available: True}
        )
        session.commit()

    def _export(
        self, img: Image.Image, object_id: str, out_dir: Path
    ) -> tuple[dict[str, dict], list[str]]:
        """Export image at applicable sizes; promotes largest to lossless high if source is below the high tier."""
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
            rec = _save_webp(resized, out_dir / f"{tier}.webp", lossless=False)
            exports[tier] = rec

            target = _size_target(size)
            if target and rec["size_bytes"] > target:
                msg = f"{object_id}/{tier}.webp: {rec['size_bytes'] / 1024:.0f} KiB exceeds {target // 1024} KiB target"
                log.warning(msg)
                warnings.append(msg)

        # If no high was produced (source ≤ 8192), promote the largest export to high
        # as a lossless copy — but only if it's small enough to be worth it
        if "high" not in exports:
            largest_rec = exports[max(exports, key=lambda t: exports[t]["width"])]
            if largest_rec["size_bytes"] < 300 * 1024:
                exports["high"] = _save_webp(
                    _resize(img, largest_rec["width"]),
                    out_dir / "high.webp",
                    lossless=True,
                )

        return exports, warnings

    def process_all(self, force: bool = False) -> None:
        """Process all textures listed in download-metadata.yaml.

        Warns about any image files in RAW_DIR not referenced by the metadata.
        Writes a global warnings file to the textures download directory.
        """
        self._global_warnings = []
        known_files = {entry["file"] for entry in self._raw_meta}

        for entry in self._raw_meta:
            if entry.get("skip"):
                continue
            src = RAW_DIR / entry["file"]
            if not src.exists():
                msg = f"listed in metadata but not found: {entry['file']}"
                log.warning(msg)
                self._global_warnings.append(msg)
                continue
            self.process(src, force=force)

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

        if not force and (out_dir / "metadata.json").exists():
            log.debug(
                "skipping %s (already processed, use force=True to reprocess)", src.name
            )
            return out_dir

        out_dir.mkdir(parents=True, exist_ok=True)

        img = _open_image(src)
        w, h = img.size

        exports, warnings = self._export(img, object_id, out_dir)

        self._global_warnings.extend(warnings)
        self._mark_texture_available(object_id)

        metadata = {
            "id": object_id,
            "source": entry["source"],
            "description": entry.get("description"),
            "type": entry["type"],
            "source_file": src.name,
            "source_dimensions": [w, h],
            "processed_at": datetime.now(UTC).isoformat(),
            "exports": exports,
        }

        (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))
        log.info("processed %s → %s (%d exports)", src.name, object_id, len(exports))

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
