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

Per-object DB state (object_type, parent, scale, has_localized, radius
overrides) is intentionally NOT fingerprinted — those fields ride into the
binary but are also republished by the `/objects` bundles every run; we
treat that as the canonical refresh path and accept that DB-only edits
won't invalidate already-written position parts.
"""

import json
from pathlib import Path

from space_map_data.constants.providers import PROVIDERS
from space_map_data.export.sidecar_io import (  # noqa: F401  (re-exported)
    matches,
    mirror_path,
    read_sidecar,
    write_atomic,
    write_sidecar,
)


# Bump when the elements encoding (writer.py / format.py columns for any
# elements-format zone) changes. Mismatch with a part's stored sidecar
# forces that part to be re-encoded.
FORMAT_VERSION = 1


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


def build_earth_part_signature(day_dir: Path) -> dict:
    """Compute the expected sidecar contents for one Earth (zoom, date, part).

    Every part within a date shares the same signature — the CSV inputs
    drive the orbital elements for every satellite that day. The signature
    only needs to differ across dates, which `day_dir` accomplishes.
    """
    return {
        "format_version": FORMAT_VERSION,
        "inputs": _day_dir_inputs(day_dir),
    }


def build_sbdb_part_signature(download_dir: Path) -> dict:
    """Compute the expected sidecar contents for one small_bodies/* part.

    The unit of cacheability is the entire SBDB download — JPL ships the
    full small-body catalog as one snapshot and our downloader replaces
    every row when fetching. So every small_bodies/* part across all zones
    shares the same signature, and a fresh SBDB pull invalidates every
    part at once (same model as a kernel update for probes).

    Reads `sbdb/metadata.json` written by `Downloader._save_metadata`. The
    `downloaded_at` timestamp alone would suffice to detect re-downloads,
    but `record_count` + `complete` are included so a sidecar from a
    partial/aborted download (`complete: false`) doesn't get conflated
    with a later complete one that happened to land at the same timestamp.
    """
    meta_path = download_dir / PROVIDERS.SBDB / "metadata.json"
    meta = json.loads(meta_path.read_text())
    return {
        "format_version": FORMAT_VERSION,
        "sbdb_snapshot": {
            "downloaded_at": meta["downloaded_at"],
            "record_count": meta["record_count"],
            "complete": meta["complete"],
        },
    }
