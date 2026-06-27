"""Run-level incremental gates for the export pipeline.

Two layers on top of the existing per-part sidecars:

* A **tier-B fingerprint** covering every input that feeds the per-object
  outputs (bundles, labels, feature details, messages). When it matches the
  previous run's, those writers are skipped wholesale and zones whose
  position signature also matches skip their DB load entirely.
* **Per-phase meta sidecars** (zone stats, chebyshev manifest, probes
  manifest) caching what the final metadata.json and prune pass need from
  skipped phases.

All meta files live in EXPORT_METADATA_DIR via `sidecar_io.mirror_path`.
A missing or mismatched meta always falls back to doing the work.
"""

import hashlib
import json
import logging
import math
from pathlib import Path

from sqlalchemy.orm import Session

from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.position.elements.celestrak_source import current_day_dirs
from space_map_data.export.position.elements.sidecar import (
    build_earth_part_signature,
    build_sbdb_part_signature,
)
from space_map_data.export.position.elements.spacetrack_source import (
    ARCHIVE_YEARS,
    archive_zip_fingerprints,
)
from space_map_data.export.position.format import VERSION as BINARY_VERSION
from space_map_data.export.position.layout import position_zone_dir
from space_map_data.export.sidecar_io import mirror_path, read_sidecar, write_sidecar
from space_map_data.models.ingest_stamp import read_ingest_stamp
from space_map_data.utils.paths import (
    DOWNLOAD_DIR,
    SOURCES_IMAGES_DIR,
    SOURCES_METADATA_DIR,
    SOURCES_POSITION_DIR,
)

logger = logging.getLogger(__name__)

# Bump to invalidate all tier-B outputs (bundle/label/feature/message shape
# changes that no input fingerprint captures).
TIER_B_VERSION = 3

_TIER_B_META = "tier_b.meta.json"
_CHEB_META = "position/chebyshev.meta.json"
_PROBES_META = "position/probes/__pass__.meta.json"
ZONE_META_NAME = "__zone__.meta.json"


def _digest(value) -> str:
    """Stable short hash of any JSON-serializable value."""
    raw = json.dumps(value, sort_keys=True, default=str).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def _file_stamp(path: Path) -> dict | None:
    """`{mtime_ns, size}` for one file, or None when missing."""
    if not path.exists():
        return None
    st = path.stat()
    return {"mtime_ns": st.st_mtime_ns, "size": st.st_size}


def _source_stamp(metadata_path: Path) -> dict | None:
    """Downloader metadata.json contents relevant to invalidation."""
    if not metadata_path.exists():
        return None
    meta = json.loads(metadata_path.read_text())
    return {
        "downloaded_at": meta.get("downloaded_at"),
        "record_count": meta.get("record_count"),
        "complete": meta.get("complete"),
    }


def _tree_digest(root: Path, glob: str = "**/*") -> str:
    """Digest of (relative name, mtime_ns, size) for every file under root."""
    if not root.exists():
        return "missing"
    entries = []
    for path in sorted(root.glob(glob)):
        if path.is_file():
            st = path.stat()
            entries.append((str(path.relative_to(root)), st.st_mtime_ns, st.st_size))
    return _digest(entries)


def kernels_digest() -> str:
    """Fingerprint of the whole SPICE kernel tree (stat-only, ~15k files)."""
    return _tree_digest(SOURCES_POSITION_DIR / "spice-kernels")


def tier_b_fingerprint(session: Session) -> dict:
    """Inputs that feed bundles/labels/features/messages.

    `ingest_stamp` covers all DB content; the source stamps cover files the
    export reads directly from the downloads tree; `kernels` covers the
    attitude blocks injected into object bundles.
    """
    return {
        "version": TIER_B_VERSION,
        "languages": list(LANGUAGES),
        "ingest_stamp": read_ingest_stamp(session),
        "wikidata": _source_stamp(SOURCES_METADATA_DIR / "wikidata" / "metadata.json"),
        "wikipedia": _source_stamp(
            SOURCES_METADATA_DIR / "wikipedia" / "metadata.json"
        ),
        "images": _source_stamp(SOURCES_IMAGES_DIR / "commons" / "metadata.json"),
        "nasa_urls": _file_stamp(
            SOURCES_METADATA_DIR / "nasa-science-urls" / "pk-to-url.json"
        ),
        "kernels": kernels_digest(),
    }


def _meta_path(out_dir: Path, rel: str) -> Path:
    return mirror_path(out_dir / rel)


def read_tier_b_meta(out_dir: Path) -> dict | None:
    return read_sidecar(_meta_path(out_dir, _TIER_B_META))


def write_tier_b_meta(
    out_dir: Path,
    fingerprint: dict,
    bundle_ns: dict,
    feature_bundle_ns: dict,
    group_bundle_ns: dict,
) -> None:
    write_sidecar(
        _meta_path(out_dir, _TIER_B_META),
        {
            "fingerprint": fingerprint,
            "bundle_ns": bundle_ns,
            "feature_bundle_ns": feature_bundle_ns,
            "group_bundle_ns": group_bundle_ns,
        },
    )


# --- zone meta -------------------------------------------------------------


def sbdb_zone_signature(cheb_covered_ids: set[str], host_ids: set[str]) -> dict:
    """Shared signature for every small_bodies/* zone.

    The tier-B gate covers DB/wikidata-derived row state; this needs the SBDB
    snapshot itself, the cheb exclusion set that shapes zone membership, and
    the moon-host set (its members are promoted into the eager zoom-0 tier, so
    a change here moves a body between zooms).
    """
    return {
        "part": build_sbdb_part_signature(DOWNLOAD_DIR),
        "cheb_covered": _digest(sorted(cheb_covered_ids)),
        "moon_hosts": _digest(sorted(host_ids)),
    }


def earth_zone_signature() -> dict:
    """Shared signature for both earth zooms.

    Covers every live day-dir's CSV fingerprints and the Space-Track archive
    zips feeding the historical weekly snapshots. A change to either re-runs
    the zone.
    """
    days = current_day_dirs(DOWNLOAD_DIR)
    return {
        "days": {iso: build_earth_part_signature(day_dir) for iso, day_dir in days},
        "archive": archive_zip_fingerprints(ARCHIVE_YEARS),
    }


def zone_meta_path(out_dir: Path, zone: str, zoom: int) -> Path:
    return mirror_path(position_zone_dir(out_dir, zone, zoom) / ZONE_META_NAME)


def _jd_to_json(value: float) -> float | None:
    return None if math.isinf(value) else value


def _jd_from_json(value: float | None, sign: int) -> float:
    return sign * math.inf if value is None else value


def encode_snapshots(snapshots: list) -> list[dict]:
    """SnapshotResult list → JSON-safe dicts (±inf validity → None)."""
    return [
        {
            "time": s.time,
            "count": s.count,
            "num_parts": s.num_parts,
            "chunk_days": s.chunk_days,
            "validity_start_jd": _jd_to_json(s.validity_start_jd),
            "validity_end_jd": _jd_to_json(s.validity_end_jd),
        }
        for s in snapshots
    ]


def decode_snapshots(raw: list[dict]) -> list[dict]:
    """Inverse of :func:`encode_snapshots`, as kwargs dicts for SnapshotResult."""
    return [
        {
            "time": s["time"],
            "count": s["count"],
            "num_parts": s["num_parts"],
            "chunk_days": s["chunk_days"],
            "validity_start_jd": _jd_from_json(s["validity_start_jd"], -1),
            "validity_end_jd": _jd_from_json(s["validity_end_jd"], 1),
        }
        for s in raw
    ]


def read_zone_meta(out_dir: Path, zone: str, zoom: int) -> dict | None:
    """Raw cached zone meta; callers compare `meta["signature"]` themselves."""
    return read_sidecar(zone_meta_path(out_dir, zone, zoom))


def write_zone_meta(
    out_dir: Path,
    zone: str,
    zoom: int,
    signature: dict,
    parent_id_type: str | None,
    snapshots: list,
) -> None:
    write_sidecar(
        zone_meta_path(out_dir, zone, zoom),
        {
            "signature": signature,
            "parent_id_type": parent_id_type,
            "snapshots": encode_snapshots(snapshots),
        },
    )


def zone_parts_exist(
    out_dir: Path, zone: str, zoom: int, snapshots: list[dict]
) -> bool:
    """True iff every part file recorded in cached stats is still on disk."""
    base = position_zone_dir(out_dir, zone, zoom)
    for snap in snapshots:
        snap_dir = base / snap["time"] if snap["time"] is not None else base
        for part in range(snap["num_parts"]):
            if not (snap_dir / f"{part}.bin.gz").exists():
                return False
    return True


# --- chebyshev meta --------------------------------------------------------


def chebyshev_signature() -> dict:
    """Inputs of the chebyshev pass: derived npz tree + chunk-grid metadata.

    DB/wikidata-derived inputs (body resolution, has_localized bits) are
    covered by the tier-B gate: the pass only skips when tier B is clean.
    """
    derived = DOWNLOAD_DIR / "derived" / "position"
    return {
        "binary_version": BINARY_VERSION,
        "npz": _tree_digest(derived / "chebyshev", "*.npz"),
        "tables_metadata": _file_stamp(derived / "tables" / "metadata.json"),
    }


def read_chebyshev_meta(out_dir: Path) -> dict | None:
    """Raw cached chebyshev meta; callers compare signatures themselves."""
    return read_sidecar(_meta_path(out_dir, _CHEB_META))


def write_chebyshev_meta(
    out_dir: Path,
    signature: dict,
    zone_manifest: dict,
    has_localized: dict[str, bool],
) -> None:
    write_sidecar(
        _meta_path(out_dir, _CHEB_META),
        {
            "signature": signature,
            "zone_manifest": zone_manifest,
            "has_localized": has_localized,
        },
    )


# --- probes meta -----------------------------------------------------------


def probes_signature() -> dict:
    """Inputs of the probes pass: kernels, events, fit-center candidates, registry.

    Same tier-B caveat as chebyshev: probe Object rows and has_localized
    bits are covered by the tier-B gate.
    """
    derived = DOWNLOAD_DIR / "derived" / "position"
    return {
        "binary_version": BINARY_VERSION,
        "kernels": kernels_digest(),
        "events": _tree_digest(SOURCES_POSITION_DIR / "probe-events", "*.json"),
        "candidates": _tree_digest(derived / "chebyshev", "*.npz"),
        "registry": _file_stamp(derived / "tables" / "probe_ids.json"),
    }


def read_probes_meta(out_dir: Path) -> dict | None:
    """Raw cached probes meta; callers compare signatures themselves."""
    return read_sidecar(_meta_path(out_dir, _PROBES_META))


def write_probes_meta(
    out_dir: Path,
    signature: dict,
    zone_manifest: dict,
    coverage: dict,
    has_localized: dict[str, bool],
) -> None:
    write_sidecar(
        _meta_path(out_dir, _PROBES_META),
        {
            "signature": signature,
            "zone_manifest": zone_manifest,
            "coverage": coverage,
            "has_localized": has_localized,
        },
    )
