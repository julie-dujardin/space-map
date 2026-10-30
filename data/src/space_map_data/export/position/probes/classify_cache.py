"""Per-probe cache of the classify pass results.

One JSON file per probe at
``EXPORT_METADATA_DIR/position/probes/_classify/{mission}/{naif_id}.json``
holds the worker result and the signature of its inputs. The signature has
the content stamps of the probe's kernels and of the generic kernels, the
NAIF ID, the zone and small-body constants and `CLASSIFY_VERSION`.
"""

import hashlib
import json
import logging
from pathlib import Path

from space_map_data.export.position.probes.sidecar import kernel_rel_path
from space_map_data.export.sidecar_io import write_atomic
from space_map_data.probes.small_bodies import (
    SMALL_BODY_TARGET_NAIF_IDS,
    SMALL_BODY_ZONE_RADIUS_KM,
)
from space_map_data.probes.zones import ALL_ZONES
from space_map_data.utils.content_stamp import content_stamps
from space_map_data.utils.paths import DOWNLOAD_DIR, EXPORT_METADATA_DIR

# Bump when `probes/trace.py` or the worker in `classify.py` changes. The
# probes export gate holds it, so a bump runs the probes pass again.
CLASSIFY_VERSION = 1

CLASSIFY_ROOT = EXPORT_METADATA_DIR / "position" / "probes" / "_classify"

logger = logging.getLogger(__name__)


def build_signatures(
    probes: list[tuple[Path, list[Path], int]], init_paths: list[Path]
) -> list[dict]:
    """One signature per entry of `probes`, in the same order.

    Probes of one mission share most kernels, so each file is stamped once.
    """
    unique = list(dict.fromkeys([*init_paths, *(k for _, ks, _ in probes for k in ks)]))
    stamps = content_stamps(unique)
    init_entries = [_kernel_entry(p, stamps) for p in init_paths]
    shared = {
        "version": CLASSIFY_VERSION,
        "params": _params_hash(),
        "init_kernels": _hash(init_entries),
    }
    return [
        {
            **shared,
            "naif_id": naif_id,
            "kernels": [_kernel_entry(k, stamps) for k in kernels],
        }
        for _, kernels, naif_id in probes
    ]


def load(mission: str, naif_id: int, signature: dict) -> dict | None:
    """The cached worker result, or None when the signature differs."""
    try:
        entry = json.loads(_path(mission, naif_id).read_bytes())
    except OSError, json.JSONDecodeError:
        return None
    if entry.get("signature") != signature:
        return None
    result = entry["result"]
    # JSON has no tuples. Give back the shape that the worker returns.
    if result["status"] == "ok":
        result["intervals"] = [tuple(iv) for iv in result["intervals"]]
        result["landed_phases"] = [tuple(p) for p in result["landed_phases"]]
    return result


def save(mission: str, naif_id: int, signature: dict, result: dict) -> None:
    payload = {"signature": signature, "result": result}
    write_atomic(_path(mission, naif_id), json.dumps(payload).encode())


def prune(keep: set[tuple[str, int]]) -> None:
    """Delete each file in a mission folder that is not the entry of a probe
    in `keep`."""
    if not CLASSIFY_ROOT.exists():
        return
    names = {f"{mission}/{naif_id}.json" for mission, naif_id in keep}
    n_removed = 0
    for mission_dir in CLASSIFY_ROOT.iterdir():
        if not mission_dir.is_dir():
            continue
        for path in mission_dir.iterdir():
            if f"{mission_dir.name}/{path.name}" not in names:
                path.unlink()
                n_removed += 1
        if not any(mission_dir.iterdir()):
            mission_dir.rmdir()
    if n_removed:
        logger.info("Probes export: pruned %d classify cache file(s)", n_removed)


def _path(mission: str, naif_id: int) -> Path:
    return CLASSIFY_ROOT / mission / f"{naif_id}.json"


def _kernel_entry(path: Path, stamps: dict[Path, dict | None]) -> dict:
    # A path relative to the downloads tree keeps the cache valid after a move.
    return {"path": kernel_rel_path(path, DOWNLOAD_DIR), **(stamps[path] or {})}


def _params_hash() -> str:
    """Hash of the constants the classification reads from `zones.py` and
    `small_bodies.py`."""
    return _hash(
        {
            "zones": [[z.key, z.barycenter_naif_id, z.r_zone_km] for z in ALL_ZONES],
            "small_bodies": list(SMALL_BODY_TARGET_NAIF_IDS),
            "small_body_radius_km": SMALL_BODY_ZONE_RADIUS_KM,
        }
    )


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:16]
