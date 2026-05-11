import json
import logging
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict, cast

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
# Per-texture scraped source metadata (written by the texture_sources downloader);
# used as a fallback for `attribution` when download-metadata.yaml doesn't provide one.
SOURCE_METADATA_PARSED_DIR = DOWNLOAD_DIR / "textures" / "source_metadata" / "parsed"
# Date-partitioned snapshots written by the earth_clouds downloader at 3h cadence.
EARTH_CLOUDS_DIR = DOWNLOAD_DIR / "textures" / "earth_clouds"
# Parallel to the Earth surface texture; the renderer layers it on top of naif-399.
EARTH_CLOUDS_OBJECT_ID = "naif-399_clouds"
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


def _webp_kwargs(lossless: bool) -> dict:
    return {"lossless": True, "method": 6} if lossless else {"quality": 80}


def _refresh_metadata_from_yaml(out_dir: Path, entry: dict, src_file_name: str) -> None:
    """Update yaml-sourced fields on an existing metadata.json without re-exporting the image.

    Covers entries written before a field existed (e.g. `organisation`,
    `attribution`) and any later yaml edits. Leaves image-derived fields
    (`source_file`, `source_dimensions`, `processed_at`, `exports`) intact.
    Silently no-ops if the file is missing — nothing to refresh.
    """
    meta_path = out_dir / "metadata.json"
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
    meta_path.write_text(json.dumps(current, indent=2))
    log.info("refreshed metadata from yaml: %s", meta_path.relative_to(PROCESSED_DIR))


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

    Used by ``_try_skip`` to force a reprocess when the yaml entry shape
    (monthly only) or the latest snapshot (clouds only) has diverged from
    the last export. Returns None for single-frame entries — their skip
    is driven by file existence and the per-export size cap.
    """
    type_ = entry.get("type")
    if type_ == "cylindrical_monthly":
        if (
            existing.get("type") != type_
            or existing.get("frames") != entry.get("months", 12)
            or existing.get("source_file") != entry["file"]
        ):
            return "yaml entry shape changed"
    elif type_ == "clouds_overlay":
        if existing.get("source_file") != entry["file"]:
            return f"new snapshot {entry['file']}"
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
    meta_path = out_dir / "metadata.json"
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
        self._raw_meta: list[dict] = yaml.safe_load(
            (DOWNLOAD_DIR / "textures" / "download-metadata.yaml").read_text()
        )["bodies"]
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
        meta_path = out_dir / "metadata.json"
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
        (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

    def process_all(self, force: bool = False) -> None:
        """Process all textures listed in download-metadata.yaml.

        Warns about any image files in RAW_DIR not referenced by the metadata.
        Writes a global warnings file to the textures download directory.
        """
        self._global_warnings = []
        self._reset_texture_available()
        known_files: set[str] = set()
        for entry in self._raw_meta:
            known_files.update(_expand_entry_files(entry))

        for entry in self._raw_meta:
            if entry.get("skip"):
                continue
            if entry.get("type") == "cylindrical_monthly":
                self._process_monthly(entry, force=force)
                continue
            src = RAW_DIR / entry["file"]
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
        exports, warnings = self._export(img, object_id, out_dir)
        self._global_warnings.extend(warnings)

        self._write_metadata(
            out_dir,
            entry,
            source_file=src.name,
            attribution_file=src.name,
            source_dims=[img.width, img.height],
            exports=exports,
        )
        log.info("processed %s → %s (%d exports)", src.name, object_id, len(exports))
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

        missing = [f for f in expected_files if not (RAW_DIR / f).exists()]
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

        for m in range(1, months + 1):
            fname = file_template.format(month=m)
            src = RAW_DIR / fname
            if not src.exists():
                continue
            img = _open_image(src)
            if source_dims is None:
                source_dims = [img.width, img.height]
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
            extra_fields={"frames": months},
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
        """Process the latest Earth cloud-cover snapshot into WebP exports.

        Reads PNGs from ``EARTH_CLOUDS_DIR`` (date tree written by the
        earth_clouds downloader at 3h cadence), picks the most recent one,
        and exports under ``PROCESSED_DIR/<EARTH_CLOUDS_OBJECT_ID>/``. The
        export sits alongside the Earth surface texture so the renderer can
        layer it on top of naif-399.

        Skip semantics mirror ``process()``: an existing export is kept
        when its recorded ``source_file`` matches the latest snapshot and
        no export busts the file cap; otherwise the latest snapshot is
        re-exported. ``force=True`` always reprocesses.
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

        src = pngs[-1]
        rel_src = src.relative_to(EARTH_CLOUDS_DIR).as_posix()

        download_meta_path = EARTH_CLOUDS_DIR / "metadata.json"
        download_meta: dict = {}
        if download_meta_path.exists():
            try:
                download_meta = json.loads(download_meta_path.read_text())
            except (OSError, json.JSONDecodeError):
                log.warning(
                    "failed to read earth_clouds metadata at %s", download_meta_path
                )

        entry = {
            "body": EARTH_CLOUDS_OBJECT_ID,
            "source": download_meta.get("source_url", ""),
            "organisation": "EUMETSAT",
            "attribution": download_meta.get("attribution"),
            "description": "Near-real-time cloud-cover overlay (3-hour cadence).",
            "type": "clouds_overlay",
            "file": rel_src,
        }
        out_dir = PROCESSED_DIR / EARTH_CLOUDS_OBJECT_ID

        if not force and self._try_skip(
            out_dir,
            entry,
            attribution_file=src.name,
            label=EARTH_CLOUDS_OBJECT_ID,
        ):
            return out_dir

        out_dir.mkdir(parents=True, exist_ok=True)
        img = _open_image(src)
        exports, warnings = self._export(img, EARTH_CLOUDS_OBJECT_ID, out_dir)
        self._global_warnings.extend(warnings)

        self._write_metadata(
            out_dir,
            entry,
            source_file=rel_src,
            attribution_file=src.name,
            source_dims=[img.width, img.height],
            exports=exports,
        )
        log.info(
            "processed clouds %s → %s (%d exports)",
            rel_src,
            EARTH_CLOUDS_OBJECT_ID,
            len(exports),
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
