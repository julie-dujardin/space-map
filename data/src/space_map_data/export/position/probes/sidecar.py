"""Sidecar metadata for incremental probe export.

Each chunk file `{zone}/{chunk_idx}.bin.gz` has a companion JSON sidecar
`{chunk_idx}.meta.json` recording the inputs that produced it:

  * `binary_version` — `format.VERSION` mirror; wire-format bumps
    auto-invalidate every chunk.
  * `fit_version` — manual bump for fit-internal changes at the same
    wire format (e.g. retuning a sizing threshold).
  * `zone_hash` — content hash of fit-affecting zone params.
  * `probes` — `{probe_id: [{path, mtime_ns, size}, …]}` per kernel.
    Kernel edits invalidate only the chunks the probe contributes to.

Atomic writes: binary then sidecar, each tempfile + rename. A partially-
completed run leaves the chunk in "regenerate next run" state.

`mtime_ns + size` is good enough as long as kernels are never rewritten
in place. Our downloader writes once; if that ever changes, switch to a
content hash here.
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
from space_map_data.probes.zones import Zone


# Bump for fit-internal changes at the same wire format. Wire-format bumps
# travel via `BINARY_VERSION` in the signature dict — don't bump here for those.
FIT_VERSION = 14


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
    probes: list[tuple[int, list[Path], int, bool]],
    download_dir: Path,
    candidates_hash: str,
) -> dict:
    """Compute the expected sidecar contents from the *planned* probe set.

    `probes` is `[(probe_id, [kernel_path, ...], object_type_ordinal,
    has_localized), ...]`. Duplicate probe_ids collapse to a single entry
    (latest wins) — the planning pass can append a probe multiple times for
    a chunk when its zone-membership intervals re-enter the chunk window.

    Per-probe header bits (`object_type_ordinal`, `has_localized`) are
    folded into the signature so that flipping either invalidates the
    chunk — those bits live in each probe's binary header and a stale
    chunk would otherwise keep the old values forever.

    `candidates_hash` summarises the set of alternate fit centers
    (moons / asteroids) that detection considered. Changes — adding a
    moon to chebyshev, removing an asteroid — invalidate every chunk so
    detection re-runs.
    """
    probe_block: dict[str, dict] = {}
    for probe_id, kernels, object_type_ordinal, has_localized in probes:
        entries = sorted(
            (_kernel_entry(k, download_dir) for k in kernels),
            key=lambda d: d["path"],
        )
        probe_block[str(probe_id)] = {
            "kernels": entries,
            "object_type_ordinal": object_type_ordinal,
            "has_localized": has_localized,
        }
    return {
        "binary_version": BINARY_VERSION,
        "fit_version": FIT_VERSION,
        "zone_hash": zone_signature(zone),
        "candidates_hash": candidates_hash,
        "probes": dict(sorted(probe_block.items())),
    }
