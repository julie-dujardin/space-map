"""Convert raw 1-D ring profile text files to lossless WebP exports.

Iterates ``DOWNLOAD_DIR/rings/<body>/ring-metadata.yaml`` for every downloaded
body, parses each channel's text file (one float per line for L channels;
whitespace-separated R G B per line for the color channel), and writes
1×N lossless WebP images plus a ``metadata.json`` to
``EXPORT_DIR/v1/rings/<object_id>/``. Mirrors the textures pipeline so the
ring metadata block in ``systems/<bary>.json`` can be assembled by the export
step from the on-disk ``metadata.json``.

The DB ``has_rings`` flag on ``Object`` is reset for every run and re-marked
per body that has a successfully processed ring bundle (same idempotency
shape as ``map_texture_available``).
"""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import yaml
from PIL import Image

from space_map_data.models.object import Object
from space_map_data.utils.db import get_session
from space_map_data.utils.paths import DOWNLOAD_DIR, EXPORT_DIR

log = logging.getLogger(__name__)

RAW_DIR = DOWNLOAD_DIR / "rings"
PROCESSED_DIR = EXPORT_DIR / "v1" / "rings"

# 8-bit WebP lossless: source values are in [0, 1] with ~7 decimal digits of
# *text* precision but were derived from 8-bit Cassini imagery, so quantizing
# to uint8 here matches the actual information content. Three.js consumes
# everything as 8-bit per channel anyway.
COLOR_CHANNEL = "color"


def _read_scalar_channel(path: Path) -> np.ndarray:
    """Read one float per line; return shape (N,) in [0, 1]."""
    arr = np.loadtxt(str(path), dtype=np.float32)
    if arr.ndim != 1:
        raise ValueError(
            f"{path.name}: expected 1-D scalar profile, got shape {arr.shape}"
        )
    return arr


def _read_color_channel(path: Path) -> np.ndarray:
    """Read whitespace-separated R G B per line; return shape (N, 3) in [0, 1]."""
    arr = np.loadtxt(str(path), dtype=np.float32)
    if arr.ndim != 2 or arr.shape[1] != 3:
        raise ValueError(
            f"{path.name}: expected (N, 3) RGB profile, got shape {arr.shape}"
        )
    return arr


def _quantize(arr: np.ndarray) -> np.ndarray:
    """Clip to [0, 1] and round to uint8. Logs the out-of-range pixel count if any."""
    n_oob = int(np.sum((arr < 0.0) | (arr > 1.0)))
    if n_oob:
        log.warning(
            "clipped %d out-of-range sample(s) to [0, 1] (min=%.4f max=%.4f)",
            n_oob,
            float(arr.min()),
            float(arr.max()),
        )
    return np.clip(arr * 255.0 + 0.5, 0, 255).astype(np.uint8)


def _save_lossless_webp(img: Image.Image, path: Path) -> dict:
    img.save(path, "webp", lossless=True, method=6)
    size = path.stat().st_size
    return {
        "file": path.name,
        "width": img.width,
        "height": img.height,
        "size_bytes": size,
    }


class RingProcessor:
    """Parse downloaded ring profiles and emit lossless WebP exports."""

    def _reset_has_rings(self) -> None:
        session = get_session()
        session.query(Object).update({Object.has_rings: False})
        session.commit()

    def _mark_has_rings(self, object_id: str) -> None:
        session = get_session()
        updated = (
            session.query(Object)
            .filter(Object.id == object_id)
            .update({Object.has_rings: True})
        )
        session.commit()
        if not updated:
            log.warning(
                "ring metadata references %s but no matching Object row exists",
                object_id,
            )

    def process_all(self, force: bool = False) -> None:
        """Process every ``rings/<body>/ring-metadata.yaml`` under DOWNLOAD_DIR.

        Quietly no-ops when ``DOWNLOAD_DIR/rings`` doesn't exist yet (no
        downloader has run). Each body is processed independently; a failing
        entry is logged but doesn't abort the run.
        """
        self._reset_has_rings()

        if not RAW_DIR.exists():
            log.info("no ring downloads at %s, skipping", RAW_DIR)
            return

        for body_dir in sorted(p for p in RAW_DIR.iterdir() if p.is_dir()):
            yaml_path = body_dir / "ring-metadata.yaml"
            if not yaml_path.exists():
                log.warning(
                    "ring directory %s has no ring-metadata.yaml, skipping",
                    body_dir.name,
                )
                continue
            try:
                self.process(yaml_path, force=force)
            except Exception:
                log.exception("failed to process rings for %s", body_dir.name)

    def process(self, metadata_yaml: Path, force: bool = False) -> Path:
        """Process one body's ring profile bundle.

        Reads ``ring-metadata.yaml`` from the body's download dir, converts
        each channel to a 1×N lossless WebP under ``EXPORT_DIR/v1/rings/<id>``,
        and writes a sibling ``metadata.json``. Returns the output directory.
        """
        meta = yaml.safe_load(metadata_yaml.read_text())
        object_id = meta["body"]
        sample_count = int(meta["sample_count"])
        channels: dict[str, str] = meta["channels"]

        out_dir = PROCESSED_DIR / object_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out_meta_path = out_dir / "metadata.json"

        if not force and out_meta_path.exists():
            log.debug(
                "skipping %s rings (already processed, use force=True)", object_id
            )
            self._mark_has_rings(object_id)
            return out_dir

        raw_dir = metadata_yaml.parent / "raw"
        exports: dict[str, dict] = {}

        for channel, filename in channels.items():
            src = raw_dir / filename
            if not src.exists():
                # Loud failure rather than swallow — a missing channel makes
                # the whole bundle unusable for the renderer.
                raise FileNotFoundError(
                    f"ring profile {src} listed in {metadata_yaml.name} but not on disk"
                )

            if channel == COLOR_CHANNEL:
                arr = _read_color_channel(src)
                if arr.shape[0] != sample_count:
                    raise ValueError(
                        f"{src.name}: {arr.shape[0]} rows, "
                        f"expected sample_count={sample_count}"
                    )
                pixels = _quantize(arr).reshape(1, sample_count, 3)
                img = Image.fromarray(pixels, mode="RGB")
            else:
                arr = _read_scalar_channel(src)
                if arr.shape[0] != sample_count:
                    raise ValueError(
                        f"{src.name}: {arr.shape[0]} samples, "
                        f"expected sample_count={sample_count}"
                    )
                pixels = _quantize(arr).reshape(1, sample_count)
                img = Image.fromarray(pixels, mode="L")

            exports[channel] = _save_lossless_webp(img, out_dir / f"{channel}.webp")
            log.debug(
                "wrote %s/%s.webp (%dx%d, %d bytes)",
                object_id,
                channel,
                exports[channel]["width"],
                exports[channel]["height"],
                exports[channel]["size_bytes"],
            )

        out_meta = {
            "id": object_id,
            "source": meta["source"],
            "organisation": meta["organisation"],
            "attribution": meta["attribution"],
            "description": meta.get("description"),
            "inner_radius_km": float(meta["inner_radius_km"]),
            "outer_radius_km": float(meta["outer_radius_km"]),
            "sample_count": sample_count,
            "color_space": "srgb",
            "processed_at": datetime.now(UTC).isoformat(),
            "channels": exports,
        }
        out_meta_path.write_text(json.dumps(out_meta, indent=2))
        log.info(
            "processed rings for %s -> %s (%d channels)",
            object_id,
            out_dir.relative_to(EXPORT_DIR),
            len(exports),
        )

        self._mark_has_rings(object_id)
        return out_dir
