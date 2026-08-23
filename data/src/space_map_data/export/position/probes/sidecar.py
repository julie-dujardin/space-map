"""Sidecar metadata for incremental probe export.

Each chunk file `{zone}/{chunk_idx}.bin.gz` has a companion JSON sidecar
`{chunk_idx}.meta.json` recording the inputs that produced it:
`binary_version` (wire-format bumps auto-invalidate), `zone_hash`
(fit-affecting zone params), and `probes` — `{probe_id: {"fit":
fit_sig_hash, "ord": int, "has_loc": bool}}`.

`FIT_VERSION`, kernel mtimes, candidates_hash, and events_hash live inside
the per-probe fit signature rather than here — a change to any of them
flips the affected probe's `fit` hash. An i18n/type-tag edit flips
`has_loc`/`ord` without invalidating the cached fit, so the chunk repacks
from cached trajectory data.

Atomic writes: binary then sidecar, each tempfile + rename.
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
from space_map_data.probes.landing_events import EVENTS_DIR
from space_map_data.probes.zones import Zone


# Bump for fit-internal changes at the same wire format. Wire-format bumps
# travel via `BINARY_VERSION` in the signature dict — don't bump here for those.
FIT_VERSION = 16

# Bump to repack every chunk from cached fits without re-fitting — for
# header-only changes the fit signatures can't see (fit-center id encoding).
# 3: propagate the pgaa/drm kernel-precedence re-fits (furnish order isn't
# part of the fit signature, so those chunks never self-dirty).
PACK_VERSION = 3


def zone_signature(zone: Zone) -> str:
    """Stable short hash of the zone parameters that affect fit output."""
    fields = {
        "chunk_days": zone.chunk_days,
        "kepler_subchunk_days": zone.kepler_subchunk_days,
        "accuracy_threshold_km": zone.accuracy_threshold_km,
        "short_orbit_threshold_km": zone.short_orbit_threshold_km,
        "short_orbit_period_s": zone.short_orbit_period_s,
        "float64_coeffs": zone.float64_coeffs,
        "fit_center_naif_id": zone.fit_center_naif_id,
    }
    # Added only when non-default so the zones that don't use them (all but
    # small-bodies) keep their historical hash and their cached fits.
    if zone.kepler_max_center_dist_km is not None:
        fields["kepler_max_center_dist_km"] = zone.kepler_max_center_dist_km
    if not zone.short_orbit_forces_kepler:
        fields["short_orbit_forces_kepler"] = False
    payload = json.dumps(fields, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def events_files_hash() -> str:
    """Hash every events JSON's `(name, mtime_ns, size)` so an edit anywhere
    in the events folder invalidates every cached fit that consults them.
    Empty string when the folder is absent (CI / first run)."""
    if not EVENTS_DIR.exists():
        return ""
    entries = [
        {"name": p.name, "mtime_ns": p.stat().st_mtime_ns, "size": p.stat().st_size}
        for p in sorted(EVENTS_DIR.glob("*.json"))
    ]
    return hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()[:16]


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
    probe_block: dict[str, dict],
) -> dict:
    """Chunk-level signature: zone params + per-probe `{fit, ord, has_loc}`,
    one entry per probe contributing a `ChunkProbeRecord`. `fit` flips when
    the trajectory must re-fit; the other two flip on a wire-header-only
    change (i18n, type tag), so the chunk repacks from cached fits.
    """
    return {
        "binary_version": BINARY_VERSION,
        "pack_version": PACK_VERSION,
        "zone_hash": zone_signature(zone),
        "probes": dict(sorted(probe_block.items())),
    }
