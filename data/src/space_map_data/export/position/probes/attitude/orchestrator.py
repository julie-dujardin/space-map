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
"""

import json
import logging
from pathlib import Path

import spiceypy

from space_map_data.download.providers.spice.probes import MISSIONS_DIR
from space_map_data.download.providers.spice.probes.attitude.ck_kernels import (
    ATTITUDE_INDEX_NAME,
)
from space_map_data.probes.probe_id import load_registry
from space_map_data.utils.paths import SOURCES_POSITION_DIR

from .extractor import extract_attitude, manifest_entry

logger = logging.getLogger(__name__)

_KERNELS_ROOT = SOURCES_POSITION_DIR / "spice-kernels"
_LSK = _KERNELS_ROOT / "lsk" / "naif0012.tls"
_PCK = _KERNELS_ROOT / "pck" / "pck00011.tpc"


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
        for probe in matched:
            try:
                _run_probe(
                    out_dir, probe, mission, frame_name, ck_paths, global_data, summary
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
    global_data: dict[str, dict],
    summary: dict[str, dict],
) -> None:
    probe_id = probe["probe_id"]
    sc_naif = next(
        src["naif_id"] for src in probe["kernel_sources"] if src["mission"] == mission
    )
    bus_instr_id = sc_naif * 1000
    probe_out_dir = out_dir / "attitude" / str(probe_id)

    result = extract_attitude(probe_out_dir, ck_paths, bus_instr_id, frame_name)
    if result.n_keyframes == 0:
        logger.info(
            "attitude: no keyframes for probe %d (mission %s)", probe_id, mission
        )
        return

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
    global_data[object_key]["attitude"] = manifest_entry(result, frame_name=frame_name)
    summary[str(probe_id)] = {
        "mission": mission,
        "frame": frame_name,
        "n_keyframes": result.n_keyframes,
        "n_files": len(result.files),
    }
