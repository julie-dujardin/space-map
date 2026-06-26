"""Walk every mission with a `_attitude_index.json` and run extraction.

Top-level entrypoint the export pipeline calls between `write_probes` and
`write_object_bundles`. For each mission directory under
`MISSIONS_DIR/<MISSION>/_attitude_index.json`:

  1. Resolve every probe whose registry `kernel_sources` references this
     mission (typically 1 probe per mission, occasionally 2 for joint
     stacks like BepiColombo MPO + MMO).
  2. Furnish LSK + PCK + the mission's CK + FK + SCLK once.
  3. Run `extract_attitude()` per probe; the writer drops chunk files
     under `out_dir/attitude/<probe_id>/`.
  4. Stuff each probe's `manifest_entry()` into the matching
     `global_data[f"probe-{probe_id}"]["attitude"]` key so the existing
     `write_object_bundles` step ships it alongside everything else the
     frontend already loads for the probe.

Kernel state is wiped between missions with `kclear` so cross-mission
SCLK reuse can't poison the second mission's CK decoding.

Attitude depends only on kernels (CK/FK/SCLK/LSK/PCK) and the wire format,
never on DB/wikidata — so each probe's `_attitude.meta.json` sidecar lets an
unchanged probe skip the (expensive) extraction and re-inject its cached
manifest. Chunks live at `v1/attitude/<probe>/`, outside `position/`, so
`remove_old_outputs` spares them for the skip to reuse.
"""

import json
import logging
from pathlib import Path

import spiceypy

from space_map_data.download.providers.spice.probes import MISSIONS_DIR
from space_map_data.download.providers.spice.probes.attitude.ck_kernels import (
    ATTITUDE_INDEX_NAME,
)
from space_map_data.export.sidecar_io import mirror_path, read_sidecar, write_sidecar
from space_map_data.probes.probe_id import load_registry
from space_map_data.utils.paths import SOURCES_POSITION_DIR

from .extractor import DEFAULT_EPS_DEG, extract_attitude, manifest_entry

logger = logging.getLogger(__name__)

_KERNELS_ROOT = SOURCES_POSITION_DIR / "spice-kernels"
_LSK = _KERNELS_ROOT / "lsk" / "naif0012.tls"
_PCK = _KERNELS_ROOT / "pck" / "pck00011.tpc"

# Bump when the extraction logic or chunk wire format changes so stale per-probe
# caches re-extract instead of re-shipping outdated keyframes.
_ATTITUDE_CACHE_VERSION = 1
_ATTITUDE_META_NAME = "_attitude.meta.json"


def _file_stamp(path: Path) -> dict | None:
    """`{mtime_ns, size}` for one kernel, or None when missing."""
    try:
        st = path.stat()
    except OSError:
        return None
    return {"mtime_ns": st.st_mtime_ns, "size": st.st_size}


def _mission_kernel_stamps(mission_dir: Path, index: dict) -> dict[str, dict | None]:
    """Stamp every kernel furnished for this mission, keyed by path."""
    paths = [_LSK, _PCK, mission_dir / index["fk"], mission_dir / index["sclk"]]
    paths += [mission_dir / name for name in index["ck_files"]]
    return {str(p): _file_stamp(p) for p in paths}


def write_attitude(out_dir: Path, global_data: dict[str, dict]) -> dict[str, dict]:
    """Extract attitude for every mission with kernels on disk; mutate
    `global_data` to add the manifest entry per probe.

    Returns `{probe_id: result_summary}` for the pipeline manifest. Empty
    dict if no attitude kernels are present — this lets the pipeline run
    happily without CK downloads in dev environments.
    """
    if not MISSIONS_DIR.exists():
        return {}

    registry = load_registry()
    probes_by_mission: dict[str, list[dict]] = {}
    for entry in registry:
        for src in entry["kernel_sources"]:
            probes_by_mission.setdefault(src["mission"], []).append(entry)

    summary: dict[str, dict] = {}
    for index_path in sorted(MISSIONS_DIR.glob(f"*/{ATTITUDE_INDEX_NAME}")):
        mission_dir = index_path.parent
        mission = mission_dir.name
        try:
            index = json.loads(index_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("attitude index %s unreadable: %s", index_path, exc)
            continue
        frame_name = index["frame_name"]

        matched = probes_by_mission.get(mission, [])
        if not matched:
            logger.info(
                "attitude: mission %s has kernels but no registry probe references it",
                mission,
            )
            continue

        try:
            _furnish_mission(mission_dir, index)
        except spiceypy.exceptions.SpiceyError as exc:
            logger.warning("attitude: furnish failed for %s: %s", mission, exc)
            spiceypy.kclear()
            continue

        ck_paths = [str(mission_dir / name) for name in index["ck_files"]]
        kernel_stamps = _mission_kernel_stamps(mission_dir, index)
        for probe in matched:
            try:
                _run_probe(
                    out_dir,
                    probe,
                    mission,
                    frame_name,
                    ck_paths,
                    kernel_stamps,
                    global_data,
                    summary,
                )
            except Exception as exc:
                # Don't let one probe's extraction abort the whole pipeline —
                # log and continue. CK / FK / frame mismatches are the most
                # likely cause and are easier to diagnose probe-by-probe.
                logger.warning(
                    "attitude: extraction failed for probe %s (mission %s): %s",
                    probe["probe_id"],
                    mission,
                    exc,
                )

        spiceypy.kclear()

    logger.info("attitude: wrote chunks for %d probes", len(summary))
    return summary


def _furnish_mission(mission_dir: Path, index: dict) -> None:
    """Furnish LSK + PCK + every CK / FK / SCLK named in the index."""
    spiceypy.kclear()
    spiceypy.furnsh(str(_LSK))
    spiceypy.furnsh(str(_PCK))
    spiceypy.furnsh(str(mission_dir / index["fk"]))
    spiceypy.furnsh(str(mission_dir / index["sclk"]))
    for ck_name in index["ck_files"]:
        spiceypy.furnsh(str(mission_dir / ck_name))


def _run_probe(
    out_dir: Path,
    probe: dict,
    mission: str,
    frame_name: str,
    ck_paths: list[str],
    kernel_stamps: dict[str, dict | None],
    global_data: dict[str, dict],
    summary: dict[str, dict],
) -> None:
    probe_id = probe["probe_id"]
    sc_naif = next(
        src["naif_id"] for src in probe["kernel_sources"] if src["mission"] == mission
    )
    bus_instr_id = sc_naif * 1000
    probe_out_dir = out_dir / "attitude" / str(probe_id)
    meta_path = mirror_path(probe_out_dir / _ATTITUDE_META_NAME)
    signature = {
        "version": _ATTITUDE_CACHE_VERSION,
        "frame": frame_name,
        "bus_instr_id": bus_instr_id,
        "eps_deg": DEFAULT_EPS_DEG,
        "kernels": kernel_stamps,
    }

    hit, manifest = _read_cache(meta_path, signature, probe_out_dir)
    if hit:
        if manifest is not None:
            _inject_manifest(probe_id, manifest, global_data)
            summary[str(probe_id)] = _summary_entry(mission, manifest, cached=True)
        else:
            logger.info(
                "attitude: probe %d (mission %s) unchanged, no keyframes (cached)",
                probe_id,
                mission,
            )
        return

    result = extract_attitude(probe_out_dir, ck_paths, bus_instr_id, frame_name)
    if result.n_keyframes == 0:
        logger.info(
            "attitude: no keyframes for probe %d (mission %s)", probe_id, mission
        )
        # Cache the empty result so a re-run doesn't re-extract it.
        write_sidecar(meta_path, {"signature": signature, "manifest": None})
        return

    manifest = manifest_entry(result, frame_name=frame_name)
    write_sidecar(meta_path, {"signature": signature, "manifest": manifest})
    _inject_manifest(probe_id, manifest, global_data)
    summary[str(probe_id)] = _summary_entry(mission, manifest, cached=False)


def _read_cache(
    meta_path: Path, signature: dict, probe_out_dir: Path
) -> tuple[bool, dict | None]:
    """`(hit, manifest)` for the cached probe extraction.

    `hit=False` → signature changed or chunks vanished; re-extract.
    `hit=True, manifest=None` → the cached run produced no keyframes.
    `hit=True, manifest=<dict>` → re-inject without recomputing.
    """
    meta = read_sidecar(meta_path)
    if meta is None or meta.get("signature") != signature:
        return False, None
    manifest = meta.get("manifest")
    if manifest is None:
        return True, None
    # Guard against a partial wipe shipping a manifest for missing chunks.
    if any(not (probe_out_dir / f["name"]).exists() for f in manifest["files"]):
        return False, None
    return True, manifest


def _inject_manifest(
    probe_id: int, manifest: dict, global_data: dict[str, dict]
) -> None:
    """Merge the attitude manifest into the probe's `__global__` object entry."""
    object_key = f"probe-{probe_id}"
    if object_key not in global_data:
        # The probe registry knows about this probe but the object exporter
        # didn't ship a global entry for it (could happen for excluded /
        # filtered probes). Skip silently rather than create an orphan entry.
        logger.info(
            "attitude: no global object entry for %s, skipping manifest injection",
            object_key,
        )
        return
    global_data[object_key]["attitude"] = manifest


def _summary_entry(mission: str, manifest: dict, *, cached: bool) -> dict:
    return {
        "mission": mission,
        "frame": manifest["frame"],
        "n_keyframes": manifest["n_keyframes"],
        "n_files": len(manifest["files"]),
        "cached": cached,
    }
