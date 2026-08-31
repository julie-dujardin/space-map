"""Bookkeeping for the SPK folders we write rather than mirror.

Three synthesisers produce kernels instead of downloading them: the two-body
extension of a stale archive, the conics solved from the Deep Space Catalog,
and the element sets read out of the Space-Track archive. All drop files into a
mission folder the export walker reads like any other, so all need the same
`_index.json` — a seed record, one entry per file carrying the provenance that
makes a re-run idempotent, and removal once a kernel stops being justified.
That bookkeeping lives here so the on-disk shape has one owner.
"""

import json
import logging
from pathlib import Path

import numpy as np
import spiceypy

from space_map_data.probes.propagation import GM_SUN

logger = logging.getLogger(__name__)

INDEX_NAME = "_index.json"
EXTRAP_SUFFIX = "-extrap.bsp"


def _index_path(mission_dir: Path) -> Path:
    return mission_dir / INDEX_NAME


def ensure_index(mission_dir: Path, mission: str) -> Path:
    """Create the folder's index if it has none. `spk_url` is null because
    nothing upstream serves these files."""
    path = _index_path(mission_dir)
    if not path.exists():
        path.write_text(
            json.dumps(
                {
                    "server": mission,
                    "mission": mission,
                    "spk_url": None,
                    "bucket": "trajectory",
                    "files": [],
                    "targets": {},
                },
                indent=2,
                sort_keys=True,
            )
        )
    return path


def record_file(
    mission_dir: Path,
    filename: str,
    naif: int,
    provenance_key: str,
    provenance: dict,
    create_missing: bool = False,
) -> None:
    """Replace any prior entry for ``filename`` so re-runs converge.

    ``create_missing`` separates the two callers on purpose: a folder we own
    outright is seeded on demand, while a synthesised kernel written beside a
    mirrored archive must not invent an index the downloader is responsible
    for — a missing one there means the mirror is in a state worth reporting.
    """
    path = _index_path(mission_dir)
    if not path.exists():
        if not create_missing:
            logger.warning(
                "synthetic kernels: %s missing %s; skipping index update",
                mission_dir,
                INDEX_NAME,
            )
            return
        ensure_index(mission_dir, mission_dir.name)

    idx = json.loads(path.read_text())
    files = [f for f in idx.get("files", []) if f.get("name") != filename]
    files.append(
        {
            "name": filename,
            "size_bytes": (mission_dir / filename).stat().st_size,
            "targets": [naif],
            provenance_key: provenance,
        }
    )
    idx["files"] = sorted(files, key=lambda f: f["name"])
    targets = idx.get("targets", {})
    targets[str(naif)] = sorted(set(targets.get(str(naif), []) + [filename]))
    idx["targets"] = targets
    path.write_text(json.dumps(idx, indent=2, sort_keys=True))


def cached_provenance(
    mission_dir: Path, filename: str, provenance_key: str
) -> dict | None:
    """The provenance block recorded for this filename, or None if absent."""
    path = _index_path(mission_dir)
    if not path.exists():
        return None
    idx = json.loads(path.read_text())
    for entry in idx.get("files", []):
        if entry.get("name") == filename:
            return entry.get(provenance_key) or {}
    return None


def drop_file(mission_dir: Path, filename: str, naif: int) -> None:
    """Remove one entry from the index, and the NAIF with it once nothing
    covers it any more."""
    path = _index_path(mission_dir)
    if not path.exists():
        return
    idx = json.loads(path.read_text())
    idx["files"] = [f for f in idx.get("files", []) if f.get("name") != filename]
    targets = idx.get("targets", {})
    if str(naif) in targets:
        remaining = [n for n in targets[str(naif)] if n != filename]
        if remaining:
            targets[str(naif)] = remaining
        else:
            targets.pop(str(naif))
    idx["targets"] = targets
    path.write_text(json.dumps(idx, indent=2, sort_keys=True))


def write_type5(
    out_path: Path,
    naif: int,
    internal_name: str,
    segments: list[tuple[tuple[float, ...], float, float, float, str]],
) -> None:
    """Write one Type 5 two-body segment per
    ``(state, epoch, first, last, segid)``.

    The epoch is passed rather than taken from ``first`` because a state is not
    always given at the start of the span it covers. Overwrites; the caller
    owns atomicity. Segment ids are truncated to CSPICE's 40-character limit."""
    if out_path.exists():
        out_path.unlink()
    handle = spiceypy.spkopn(str(out_path), internal_name[:60], 0)
    try:
        for state6, epoch, first, last, segid in segments:
            spiceypy.spkw05(
                handle=handle,
                body=naif,
                center=10,
                inframe="ECLIPJ2000",
                first=first,
                last=last,
                segid=segid[:40],
                gm=GM_SUN,
                n=1,
                states=np.array([list(state6)], dtype=float),
                epochs=np.array([epoch], dtype=float),
            )
    finally:
        spiceypy.spkcls(handle)


# WGS-72, the model the element sets are fitted against; SGP4 reproduces the
# fit only when evaluated with the same constants. Order is the one spkw10
# reads: J2, J3, J4, KE, QO, SO, ER, AE.
_WGS72_GEOPHYSICAL: tuple[float, ...] = (
    1.082616e-3,
    -2.53881e-6,
    -1.65597e-6,
    7.43669161e-2,
    120.0,
    78.0,
    6378.135,
    1.0,
)


def write_type10(
    out_path: Path,
    naif: int,
    internal_name: str,
    segments: list[tuple[list[float], list[list[float]], str]],
) -> None:
    """Write one Type 10 segment per ``(epochs, element sets, segid)`` run.

    Type 10 stores the element sets themselves and lets SPICE run its own
    SGP4/SDP4 over them, so nothing here samples a trajectory or rotates TEME
    into J2000 — both are the toolkit's job, and both are places a hand-rolled
    version would quietly differ from the model the elements were fitted to.

    One segment per contiguous run, so a break in the catalogue's tracking
    stays a break: SPICE answers from the nearest element set within a segment,
    which across a year-long hole would read as coverage.

    Epochs must increase strictly. Overwrites; the caller owns atomicity.
    """
    if out_path.exists():
        out_path.unlink()
    handle = spiceypy.spkopn(str(out_path), internal_name[:60], 0)
    try:
        for epochs, elements, segid in segments:
            flat = [value for element_set in elements for value in element_set]
            spiceypy.spkw10(
                handle=handle,
                body=naif,
                center=399,
                inframe="J2000",
                first=epochs[0],
                last=epochs[-1],
                segid=segid[:40],
                consts=np.array(_WGS72_GEOPHYSICAL, dtype=float),
                n=len(epochs),
                elems=np.array(flat, dtype=float),
                epochs=np.array(epochs, dtype=float),
            )
    finally:
        spiceypy.spkcls(handle)


__all__ = [
    "EXTRAP_SUFFIX",
    "INDEX_NAME",
    "cached_provenance",
    "drop_file",
    "ensure_index",
    "record_file",
    "write_type5",
    "write_type10",
]
