"""Sidecar metadata for incremental probe export.

Each chunk file `{zone}/{chunk_idx}.bin.gz` has a companion JSON sidecar
`{chunk_idx}.meta.json` recording the inputs that produced it:

  * `fit_version` — bumped manually whenever sizing.py / writer.py / format.py
    probe-encoding logic changes. Mismatch invalidates every chunk.
  * `zone_hash` — content hash of the zone parameters that affect fit
    output (chunk_years, subchunk_days, threshold, float64, fit_center, …).
    Catches zone-config edits without a manual bump.
  * `probes` — `{probe_id: [{path, mtime_ns, size}, …]}` for every kernel
    that fed into this chunk. Adding/removing/editing a kernel invalidates
    only the chunks that probe contributes to.

Atomic writes: binary then sidecar, each tempfile + rename. A partially-
completed run can leave a chunk with a stale sidecar (or none) — both are
treated as "regenerate" on the next run.

`mtime_ns + size` is good enough as long as kernels are never rewritten
in place. Our downloader writes once; if that ever changes, switch to a
content hash here.
"""

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path

from space_map_data.probes.zones import Zone

logger = logging.getLogger(__name__)


# Bump when sizing.py / writer.py / format.py probe-encoding logic changes.
# Mismatch with a chunk's stored sidecar forces that chunk to be re-fitted.
#
# v2 (2026-05-14): writer now furnshes mission kernels BEFORE generic SPKs
# so modern planetary ephemerides (de440 / sat441) win over a mission's
# bundled-from-the-1970s planetary data — Pioneer 11 Saturn dropped from
# 1271 km to ~0 km error.
# v3 (2026-05-14): classify_trace truncates the trailing landed phase so
# landed missions (Phoenix, InSight, MGS post-aerobrake) don't include
# the cruise→surface kernel-precedence step that polynomial fits can't
# capture — Phoenix Mars max dropped from 123,096 km to fitter floor.
FIT_VERSION = 3


def zone_signature(zone: Zone) -> str:
    """Stable short hash of the zone parameters that affect fit output."""
    payload = json.dumps(
        {
            "chunk_years": zone.chunk_years,
            "kepler_subchunk_days": zone.kepler_subchunk_days,
            "accuracy_threshold_km": zone.accuracy_threshold_km,
            "short_orbit_threshold_km": zone.short_orbit_threshold_km,
            "short_orbit_period_s": zone.short_orbit_period_s,
            "float64_coeffs": zone.float64_coeffs,
            "fit_center_naif_id": zone.fit_center_naif_id,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _kernel_entry(path: Path, download_dir: Path) -> dict:
    """One kernel as `{path, mtime_ns, size}`, with the path made relative
    to `download_dir` so the sidecar survives moving the data tree."""
    try:
        rel = str(path.resolve().relative_to(download_dir.resolve()))
    except ValueError:
        rel = str(path)
    st = path.stat()
    return {"path": rel, "mtime_ns": st.st_mtime_ns, "size": st.st_size}


def build_chunk_signature(
    zone: Zone,
    probes: list[tuple[int, list[Path]]],
    download_dir: Path,
) -> dict:
    """Compute the expected sidecar contents from the *planned* probe set.

    `probes` is `[(probe_id, [kernel_path, ...]), ...]`. Duplicate probe_ids
    collapse to a single entry (latest wins) — the planning pass can append
    a probe multiple times for a chunk when its zone-membership intervals
    re-enter the chunk window.
    """
    probe_block: dict[str, list[dict]] = {}
    for probe_id, kernels in probes:
        entries = sorted(
            (_kernel_entry(k, download_dir) for k in kernels),
            key=lambda d: d["path"],
        )
        probe_block[str(probe_id)] = entries
    return {
        "fit_version": FIT_VERSION,
        "zone_hash": zone_signature(zone),
        "probes": dict(sorted(probe_block.items())),
    }


def read_sidecar(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Sidecar %s unreadable (%s); treating as missing", path, e)
        return None


def matches(path: Path, expected: dict) -> bool:
    """True iff the on-disk sidecar equals `expected`."""
    return read_sidecar(path) == expected


def write_atomic(path: Path, content: bytes) -> None:
    """Tempfile + rename in the destination dir — crash-safe."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_sidecar(path: Path, signature: dict) -> None:
    write_atomic(path, json.dumps(signature, sort_keys=True, indent=2).encode())
