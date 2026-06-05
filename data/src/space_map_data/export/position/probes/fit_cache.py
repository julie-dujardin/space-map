"""Per-probe fit cache for incremental probe export.

Stores one fitted `ChunkProbeRecord` per (probe_id, zone, chunk_idx) under
``EXPORT_METADATA_DIR/position/probes/_fits/{probe_id}/{zone}/{chunk_idx}.fit``
with a sibling `.fit.meta.json` signature. The fit pass reads the cache and
only re-fits when the per-probe signature doesn't match — so a kernel edit
on one probe no longer forces re-fits of the unchanged probes that happen
to share its chunks.

Pickle is used for the binary because the payload is internal (never shipped
to clients) and the dataclasses + numpy arrays serialize cleanly. Any schema
change to `ChunkProbeRecord`, `SubChunkFit`, or `LandedFit` must bump
`INTERMEDIATE_VERSION`.
"""

import hashlib
import json
import logging
import pickle
import shutil
from pathlib import Path

from space_map_data.export.position.probes.plan import ChunkProbeRecord
from space_map_data.export.position.probes.sidecar import (
    FIT_VERSION,
    _kernel_entry,
    zone_signature,
)
from space_map_data.export.sidecar_io import write_atomic
from space_map_data.probes.zones import Zone
from space_map_data.utils.paths import EXPORT_METADATA_DIR

INTERMEDIATE_VERSION = 1

FITS_ROOT = EXPORT_METADATA_DIR / "position" / "probes" / "_fits"

logger = logging.getLogger(__name__)


def fit_path(probe_id: int, zone_key: str, chunk_idx: int) -> Path:
    return FITS_ROOT / str(probe_id) / zone_key / f"{chunk_idx}.fit"


def sig_path(probe_id: int, zone_key: str, chunk_idx: int) -> Path:
    return FITS_ROOT / str(probe_id) / zone_key / f"{chunk_idx}.fit.meta.json"


def build_fit_signature(
    zone: Zone,
    kernels: list[Path],
    download_dir: Path,
    candidates_hash: str,
    events_hash: str,
    has_flying: bool,
    has_landed: bool,
) -> dict:
    """Per-probe signature for the cached `ChunkProbeRecord` — captures only
    inputs that affect the FIT (trajectory data), not the wire-header bits.

    `candidates_hash` only folds in when the probe has a flying contribution
    (fit-center detection only runs for those). `events_hash` only when the
    probe has a landed contribution. This keeps invalidation tight: a Mercury
    events JSON edit doesn't re-fit Voyager's interplanetary fits, and a
    candidates-list edit for a zone with no flying-only probes doesn't
    re-fit pure landed probes that share its chunks.

    `object_type_ordinal` / `has_localized` are deliberately NOT in this
    signature — they live in `sidecar.build_chunk_signature`'s per-probe
    block so an i18n change repacks the chunk binary (cheap) without
    re-fitting the trajectory.
    """
    entries = sorted(
        (_kernel_entry(k, download_dir) for k in kernels),
        key=lambda d: d["path"],
    )
    sig: dict = {
        "fit_version": FIT_VERSION,
        "intermediate_version": INTERMEDIATE_VERSION,
        "zone_hash": zone_signature(zone),
        "kernels": entries,
    }
    if has_flying:
        sig["candidates_hash"] = candidates_hash
    if has_landed:
        sig["events_hash"] = events_hash
    return sig


def signature_hash(sig: dict) -> str:
    """Short stable hash of a fit signature — folded into the chunk sidecar
    so the chunk repacks iff any of its probes' fits changed."""
    return hashlib.sha256(json.dumps(sig, sort_keys=True).encode()).hexdigest()[:16]


def read_sig(probe_id: int, zone_key: str, chunk_idx: int) -> dict | None:
    path = sig_path(probe_id, zone_key, chunk_idx)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def is_cached(probe_id: int, zone_key: str, chunk_idx: int, expected_sig: dict) -> bool:
    """True iff the on-disk signature matches `expected_sig`. The `.fit`
    binary may or may not exist alongside it — sig-only entries mark
    "tried (probe, chunk), produced no record" so the next export can
    skip re-trying. `load` returns None in that case.
    """
    return read_sig(probe_id, zone_key, chunk_idx) == expected_sig


def load(probe_id: int, zone_key: str, chunk_idx: int) -> ChunkProbeRecord | None:
    path = fit_path(probe_id, zone_key, chunk_idx)
    try:
        return pickle.loads(path.read_bytes())
    except (OSError, pickle.UnpicklingError, EOFError, AttributeError):
        return None


def save(
    probe_id: int,
    zone_key: str,
    chunk_idx: int,
    record: ChunkProbeRecord | None,
    sig: dict,
) -> None:
    """Write `.fit` (pickled record) + `.fit.meta.json` (signature).

    `record=None` means the probe tried this (zone, chunk) but produced no
    output (every flying sub-chunk uncoverable, landed fit failed, …). We
    still save the signature so the next export skips re-trying; any prior
    `.fit` file is removed so a future signature match doesn't accidentally
    revive stale data.
    """
    fp = fit_path(probe_id, zone_key, chunk_idx)
    if record is None:
        fp.unlink(missing_ok=True)
    else:
        write_atomic(
            fp,
            pickle.dumps(record, protocol=pickle.HIGHEST_PROTOCOL),
        )
    write_atomic(
        sig_path(probe_id, zone_key, chunk_idx),
        json.dumps(sig, sort_keys=True, indent=2).encode(),
    )


def prune_orphans(expected_keys: set[tuple[int, str, int]]) -> None:
    """Walk `_fits/` and delete entries (or whole probe / zone subtrees) not
    in `expected_keys = {(probe_id, zone_key, chunk_idx), ...}`.

    A probe disappears from `expected_keys` when it's no longer in the
    classified plans (mission kernel removed, probe demoted, …). A chunk
    disappears when the probe's coverage shifted off it. Either way the
    stale `.fit` would otherwise accumulate forever and the next chunk
    repack would still pull it via `collect_for_repack` if the probe ever
    re-touched the chunk.
    """
    if not FITS_ROOT.exists():
        return
    expected_probes = {pid for pid, _, _ in expected_keys}
    expected_zone_chunks: dict[int, set[tuple[str, int]]] = {}
    for pid, zone_key, chunk_idx in expected_keys:
        expected_zone_chunks.setdefault(pid, set()).add((zone_key, chunk_idx))

    n_probes_removed = 0
    n_chunks_removed = 0
    for probe_dir in FITS_ROOT.iterdir():
        if not probe_dir.is_dir():
            continue
        try:
            probe_id = int(probe_dir.name)
        except ValueError:
            continue
        if probe_id not in expected_probes:
            shutil.rmtree(probe_dir)
            n_probes_removed += 1
            continue
        kept = expected_zone_chunks.get(probe_id, set())
        for zone_dir in probe_dir.iterdir():
            if not zone_dir.is_dir():
                continue
            zone_key = zone_dir.name
            for fit_file in zone_dir.glob("*.fit"):
                try:
                    chunk_idx = int(fit_file.stem)
                except ValueError:
                    continue
                if (zone_key, chunk_idx) in kept:
                    continue
                fit_file.unlink(missing_ok=True)
                sig_path(probe_id, zone_key, chunk_idx).unlink(missing_ok=True)
                n_chunks_removed += 1
            # Sigs without their fit twin (sig-only "tried but empty" entries)
            for sig_file in zone_dir.glob("*.fit.meta.json"):
                stem = sig_file.name.removesuffix(".fit.meta.json")
                try:
                    chunk_idx = int(stem)
                except ValueError:
                    continue
                if (zone_key, chunk_idx) in kept:
                    continue
                sig_file.unlink(missing_ok=True)
                n_chunks_removed += 1
            try:
                zone_dir.rmdir()
            except OSError:
                pass
    if n_probes_removed or n_chunks_removed:
        logger.info(
            "Probes export: pruned %d orphan probe dir(s) + %d orphan (zone, "
            "chunk) entr(ies) from fit cache",
            n_probes_removed,
            n_chunks_removed,
        )
