"""Convert raw 1-D ring profile text files to a single lossless WebP strip.

Iterates ``DOWNLOAD_DIR/rings/<dir>/ring-metadata.yaml`` for every downloaded
bundle, parses each channel's text file (one float per line for L channels;
whitespace-separated R G B per line for the color channel), and writes one
5×N ``strip.webp`` (one row per channel, order in ``STRIP_ROWS``) plus a
``metadata.json`` to ``EXPORT_DIR/v1/rings/<object_id>/<bundle>/``. One file
per bundle keeps it to a single request; the client splits the rows back into
separate textures after decode, so per-channel filtering is unaffected.
Mirrors the textures pipeline so the ring metadata block in
``systems/<bary>.json`` can be assembled by the export step from the on-disk
``metadata.json``.

A body may own several radially disjoint bundles — Saturn's measured main
rings plus the synthetic D ring inside them and tenuous rings outside — each
with its own sample density and intensity/thickness scale, which is how one
export holds both a τ~5 B ring and a τ~5e-6 E ring.

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

from space_map_data.export.sidecar_io import mirror_path
from space_map_data.models.object import Object
from space_map_data.utils.db import get_session
from space_map_data.utils.paths import EXPORT_DIR, SOURCES_TEXTURES_DIR

log = logging.getLogger(__name__)

RAW_DIR = SOURCES_TEXTURES_DIR / "rings"
PROCESSED_DIR = EXPORT_DIR / "v1" / "rings"

# 8-bit WebP lossless: source values are in [0, 1] with ~7 decimal digits of
# *text* precision but were derived from 8-bit Cassini imagery, so quantizing
# to uint8 here matches the actual information content. Three.js consumes
# everything as 8-bit per channel anyway.
COLOR_CHANNEL = "color"

# Row assignment inside strip.webp; scalar channels are replicated to RGB.
# ``thickness`` (vertical extent profile, × thickness_scale_km = km) is only
# present for bundles that declare it — measured Saturn data has none.
STRIP_ROWS: dict[str, int] = {
    "color": 0,
    "backscattered": 1,
    "forwardscattered": 2,
    "unlitside": 3,
    "transparency": 4,
}
OPTIONAL_ROWS = ("thickness",)
STRIP_FILE = "strip.webp"


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


def _refresh_credits(out_meta_path: Path, meta: dict) -> None:
    """Patch yaml-sourced credit fields (license, attribution, …) onto an
    existing metadata.json without re-encoding the channels — so credit edits
    ship on a skip run, mirroring the textures ``refresh_metadata_from_yaml``."""
    try:
        current = json.loads(out_meta_path.read_text())
    except (OSError, json.JSONDecodeError):
        return
    desired = {
        "sources": meta["sources"],
        "description": meta.get("description"),
    }
    if all(current.get(k) == v for k, v in desired.items()):
        return
    current.update(desired)
    out_meta_path.write_text(json.dumps(current, indent=2))
    log.info(
        "refreshed ring credits from yaml: %s/metadata.json", out_meta_path.parent.name
    )


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

        Quietly no-ops when ``RAW_DIR`` doesn't exist yet (no downloader has
        run). Each body is processed independently; a failing entry is logged
        but doesn't abort the run.
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
        bundle = meta.get("bundle")
        if not bundle:
            bundle = "primary"
            log.warning(
                "%s declares no bundle name, defaulting to %r",
                metadata_yaml.parent.name,
                bundle,
            )

        out_dir = PROCESSED_DIR / object_id / bundle
        out_dir.mkdir(parents=True, exist_ok=True)
        out_meta_path = mirror_path(out_dir / "metadata.json")
        out_meta_path.parent.mkdir(parents=True, exist_ok=True)

        if not force and out_meta_path.exists():
            log.debug(
                "skipping %s rings (already processed, use force=True)", object_id
            )
            # Still ship yaml-only credit edits (e.g. license) without re-encoding.
            _refresh_credits(out_meta_path, meta)
            self._mark_has_rings(object_id)
            return out_dir

        raw_dir = metadata_yaml.parent
        missing = set(STRIP_ROWS) - set(channels)
        if missing:
            # Loud failure rather than swallow — a missing channel makes the
            # whole bundle unusable for the renderer.
            raise ValueError(
                f"{metadata_yaml}: channels {sorted(missing)} absent from yaml"
            )

        strip_rows = dict(STRIP_ROWS)
        for extra in OPTIONAL_ROWS:
            if extra in channels:
                strip_rows[extra] = len(strip_rows)

        rows = np.zeros((len(strip_rows), sample_count, 3), dtype=np.uint8)
        for channel, row in strip_rows.items():
            src = raw_dir / channels[channel]
            if not src.exists():
                raise FileNotFoundError(
                    f"ring profile {src} listed in {metadata_yaml.name} but not on disk"
                )
            if channel == COLOR_CHANNEL:
                arr = _read_color_channel(src)
            else:
                arr = _read_scalar_channel(src)
            if arr.shape[0] != sample_count:
                raise ValueError(
                    f"{src.name}: {arr.shape[0]} samples, "
                    f"expected sample_count={sample_count}"
                )
            q = _quantize(arr)
            rows[row] = q if q.ndim == 2 else q[:, None]

        # Clears leftovers from older layouts (per-channel files, non-bundled strips).
        for stale in (*out_dir.glob("*.webp"), *out_dir.parent.glob("*.webp")):
            if stale.name != STRIP_FILE or stale.parent != out_dir:
                stale.unlink()
                log.info(
                    "removed stale ring export %s",
                    stale.relative_to(PROCESSED_DIR),
                )

        strip = _save_lossless_webp(
            Image.fromarray(rows, mode="RGB"), out_dir / STRIP_FILE
        )
        strip["rows"] = strip_rows
        log.debug(
            "wrote %s/%s (%dx%d, %d bytes)",
            object_id,
            STRIP_FILE,
            strip["width"],
            strip["height"],
            strip["size_bytes"],
        )

        out_meta = {
            "id": object_id,
            "bundle": bundle,
            "sources": meta["sources"],
            "description": meta.get("description"),
            "inner_radius_km": float(meta["inner_radius_km"]),
            "outer_radius_km": float(meta["outer_radius_km"]),
            "sample_count": sample_count,
            # Synthetic bundles store channels normalised so 8-bit survives
            # τ ~1e-6; stored × intensity_scale = physical. Measured data is 1.
            "intensity_scale": float(meta.get("intensity_scale", 1.0)),
            # 0 = no thickness channel; else km per unit of the thickness row.
            "thickness_scale_km": float(meta.get("thickness_scale_km", 0.0)),
            "color_space": "srgb",
            "processed_at": datetime.now(UTC).isoformat(),
            "strip": strip,
        }
        out_meta_path.write_text(json.dumps(out_meta, indent=2))
        log.info(
            "processed rings for %s -> %s (%d rows)",
            object_id,
            out_dir.relative_to(EXPORT_DIR),
            len(strip_rows),
        )

        self._mark_has_rings(object_id)
        return out_dir
