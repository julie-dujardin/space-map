"""Sidecar metadata for incremental elements-zone exports.

Each part file under an incremental elements zone has a companion JSON sidecar
`{part}.meta.json` recording the inputs that produced it. Two zone families
share the format:

  * `earth/{zoom}/{date}/{part}.bin.gz` — see :func:`build_earth_part_signature`.
    Fingerprints the CelesTrak CSVs in the per-day download dir.
  * `small_bodies/{class}/{zoom}/{part}.bin.gz` — see :func:`build_sbdb_part_signature`.
    Fingerprints the SBDB snapshot metadata (downloaded_at + record_count). A
    new full SBDB pull replaces every row at once, so every part shares the
    same signature within an export, and a re-download invalidates all parts.

Both shapes carry `format_version` so a writer/encoding change invalidates
every part regardless of source freshness.

Most per-object DB state (object_type, parent, scale, radius overrides) is
intentionally NOT fingerprinted — those fields ride into the binary but are
also republished by the `/objects` bundles every run; we treat that as the
canonical refresh path and accept that DB-only edits won't invalidate
already-written position parts. The `has_localized` gate byte is the lone
exception (see :func:`has_localized_digest`): it decides whether the frontend
fetches the localized bundle at all, so a stale byte hides the refreshed
`/objects` data instead of being healed by it.
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


# Bump when the elements encoding OR row-membership rules change in a way the
# binary VERSION bump doesn't already capture (e.g. column reordering at the
# same VERSION, or the earth overlay starting to keep satcat-only objects).
# Otherwise rely on BINARY_VERSION going into the signature — any wire-format
# bump (probe header growth, new fields) invalidates every elements part too.
FORMAT_VERSION = 2


def _file_entry(path: Path, day_dir: Path) -> dict:
    """One CSV input as `{name, mtime_ns, size}`, name relative to day_dir."""
    rel = str(path.relative_to(day_dir))
    st = path.stat()
    return {"name": rel, "mtime_ns": st.st_mtime_ns, "size": st.st_size}


def _day_dir_inputs(day_dir: Path) -> list[dict]:
    """Fingerprint every CelesTrak CSV in `day_dir` that feeds the export.

    Mirrors `celestrak_source._load_day`: `gp-active.csv` at the root, then
    every `groups/*.csv`. Sorted by relative name so the list is stable
    across runs regardless of filesystem iteration order.
    """
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

    Folded into both part signatures so a body gaining/losing localized data
    (e.g. a freshly matched QID) re-encodes its part. Other DB-derived columns
    skip this on purpose — they refresh via `/objects` — but this byte gates
    that very fetch, so it must invalidate the binary itself.
    """
    bits = bytes(1 if has_localized.get(oid) else 0 for oid in object_ids)
    return hashlib.sha256(bits).hexdigest()[:16]


def build_earth_part_signature(day_dir: Path) -> dict:
    """Compute the expected sidecar contents for one Earth (zoom, date, part).

    Every part within a date shares the same signature — the CSV inputs
    drive the orbital elements for every satellite that day. The signature
    only needs to differ across dates, which `day_dir` accomplishes.
    """
    return {
        "format_version": FORMAT_VERSION,
        "binary_version": BINARY_VERSION,
        "inputs": _day_dir_inputs(day_dir),
    }


def build_earth_archive_part_signature(date_iso: str) -> dict:
    """Sidecar contents for one historical (archive-sourced) Earth week.

    Historical weeks are distilled from the Space-Track year zips, not the
    CelesTrak day CSVs, so they fingerprint the zip(s) feeding the week instead
    of a day-dir. The zips are immutable once downloaded; a re-download (new
    mtime/size) invalidates the week.
    """
    from space_map_data.export.position.elements.spacetrack_source import (
        week_zip_fingerprints,
    )

    return {
        "format_version": FORMAT_VERSION,
        "binary_version": BINARY_VERSION,
        "archive_inputs": week_zip_fingerprints(date_iso),
    }


def build_sbdb_part_signature(download_dir: Path) -> dict:
    """Compute the expected sidecar contents for one small_bodies/* part.

    The unit of cacheability is the whole SBDB mirror: every
    small_bodies/* part across all zones shares the same signature, and
    any mirror change invalidates every part at once (same model as a
    kernel update for probes).

    Reads `sbdb/metadata.json`; the incremental downloader bumps its
    `downloaded_at` only when a sync actually changed rows, so no-op
    syncs don't invalidate parts. `record_count` + `complete` are
    included so a sidecar from a partial mirror (`complete: false`)
    doesn't get conflated with a later complete one that happened to
    land at the same timestamp.
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
