"""Sidecar metadata for incremental elements-zone exports.

Each part file has a companion `{part}.meta.json` recording the inputs that
produced it, so an unchanged part can skip re-encoding. `earth/...` parts
fingerprint the per-day CelesTrak CSVs; `small_bodies/...` parts fingerprint
the SBDB snapshot metadata (one signature per export — a full pull replaces
every row at once). Both carry `format_version` so an encoding change
invalidates every part regardless of source freshness.

Most per-object DB state (object_type, parent, scale, radius overrides) is
NOT fingerprinted — it's republished by `/objects` every run, treated as the
canonical refresh path. `has_localized` is the exception: it gates whether
the frontend even fetches the localized bundle, so a stale byte would hide
data `/objects` already refreshed.
"""

import hashlib
import json
from pathlib import Path

from space_map_data.export.position.format import VERSION as BINARY_VERSION
from space_map_data.export.sidecar_io import (  # noqa: F401  (re-exported)
    matches,
    mirror_path,
    read_sidecar,
    write_atomic,
    write_sidecar,
)


# Bump for an encoding/row-membership change the binary VERSION bump doesn't
# already cover. BINARY_VERSION is also in the signature, so any wire-format
# bump invalidates every elements part too.
FORMAT_VERSION = 2


def _file_entry(path: Path, day_dir: Path) -> dict:
    """One CSV input as `{name, mtime_ns, size}`, name relative to day_dir."""
    rel = str(path.relative_to(day_dir))
    st = path.stat()
    return {"name": rel, "mtime_ns": st.st_mtime_ns, "size": st.st_size}


def _day_dir_inputs(day_dir: Path) -> list[dict]:
    """Fingerprint every CelesTrak CSV in `day_dir`, mirroring
    `celestrak_source._load_day`'s file set. Sorted for stable ordering."""
    entries: list[dict] = []
    gp_active = day_dir / "gp-active.csv"
    if gp_active.exists():
        entries.append(_file_entry(gp_active, day_dir))
    groups_dir = day_dir / "groups"
    if groups_dir.exists():
        for csv_path in sorted(groups_dir.glob("*.csv")):
            entries.append(_file_entry(csv_path, day_dir))
    entries.sort(key=lambda e: e["name"])
    return entries


def has_localized_digest(object_ids: list[str], has_localized: dict[str, bool]) -> str:
    """Digest of the part's `has_localized` gate bits, in binary row order.

    Folded into both signatures so a body gaining/losing localized data
    re-encodes its part — unlike other DB-derived columns, this byte gates
    the `/objects` fetch itself, so it must invalidate the binary.
    """
    bits = bytes(1 if has_localized.get(oid) else 0 for oid in object_ids)
    return hashlib.sha256(bits).hexdigest()[:16]


def build_earth_part_signature(day_dir: Path) -> dict:
    """Expected sidecar contents for one Earth (zoom, date, part). Every part
    within a date shares this signature — the CSV inputs drive that day's
    elements for every satellite."""
    return {
        "format_version": FORMAT_VERSION,
        "binary_version": BINARY_VERSION,
        "inputs": _day_dir_inputs(day_dir),
    }


def build_earth_archive_part_signature(date_iso: str) -> dict:
    """Sidecar contents for one historical Earth week, distilled from the
    Space-Track year zips rather than CelesTrak day CSVs — fingerprints the
    zip(s) feeding the week instead of a day-dir."""
    from space_map_data.export.position.elements.spacetrack_source import (
        week_zip_fingerprints,
    )

    return {
        "format_version": FORMAT_VERSION,
        "binary_version": BINARY_VERSION,
        "archive_inputs": week_zip_fingerprints(date_iso),
    }


def build_sbdb_part_signature(download_dir: Path) -> dict:
    """Expected sidecar contents for one small_bodies/* part.

    The unit of cacheability is the whole SBDB mirror — every part shares
    this signature, and any mirror change invalidates all of them at once.
    `downloaded_at` only bumps on an actual row change, so no-op syncs don't
    invalidate parts; `complete` keeps a partial-mirror sidecar from being
    conflated with a later complete one at the same timestamp.
    """
    meta_path = download_dir / "sources" / "position" / "sbdb" / "metadata.json"
    meta = json.loads(meta_path.read_text())
    return {
        "format_version": FORMAT_VERSION,
        "binary_version": BINARY_VERSION,
        "sbdb_snapshot": {
            "downloaded_at": meta["downloaded_at"],
            "record_count": meta["record_count"],
            "complete": meta["complete"],
        },
    }
