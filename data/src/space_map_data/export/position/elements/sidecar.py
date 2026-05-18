"""Sidecar metadata for incremental Earth-zone export.

Each part file `earth/{zoom}/{date}/{part}.bin.gz` has a companion JSON
sidecar `{part}.meta.json` recording the inputs that produced it:

  * `format_version` — bumped when the SGP4 elements encoding (writer.py /
    format.py columns for the Earth zone) changes. Mismatch invalidates
    every part on disk.
  * `inputs` — `[{name, mtime_ns, size}, …]` for every CelesTrak CSV in
    the day-dir (`gp-active.csv` + `groups/*.csv`). The downloader writes
    each day-dir once and never edits in place, so `mtime_ns + size` is a
    sufficient fingerprint without rehashing megabytes of CSV on every run.

Per-object DB state (object_type, parent, scale, has_localized, radius
overrides) is intentionally NOT fingerprinted here — those fields ride
into the binary but are also republished by the `/objects` bundles every
run; we treat that as the canonical refresh path and accept that DB
edits won't invalidate already-written position parts.
"""

from pathlib import Path

from space_map_data.export.sidecar_io import (  # noqa: F401  (re-exported)
    matches,
    mirror_path,
    read_sidecar,
    write_atomic,
    write_sidecar,
)


# Bump when the elements/SGP4 encoding (writer.py / format.py columns for
# the Earth zone) changes. Mismatch with a part's stored sidecar forces
# that part to be re-encoded.
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


def build_part_signature(day_dir: Path) -> dict:
    """Compute the expected sidecar contents for one (zoom, date, part).

    Every part within a date shares the same signature — the CSV inputs
    drive the orbital elements for every satellite that day. The signature
    only needs to differ across dates, which `day_dir` accomplishes.
    """
    return {
        "format_version": FORMAT_VERSION,
        "inputs": _day_dir_inputs(day_dir),
    }
