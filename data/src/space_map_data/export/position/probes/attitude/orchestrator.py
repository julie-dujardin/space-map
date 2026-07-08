"""Walk every mission with a `_attitude_index.json` and run extraction.

Top-level entrypoint the export pipeline calls between `write_probes` and
`write_object_bundles`. The parent process plans the work: it resolves each
mission's probes from the registry, cache-checks every probe against its
`_attitude.meta.json` sidecar, and re-injects cached manifests. Cache misses
are grouped per mission and fanned out to a `ProcessPoolExecutor` — SPICE
state is per-process, so each worker furnishes its own mission kernel set
(LSK + PCK + CK + FK + SCLK), extracts every planned probe, writes chunks +
sidecar, and returns the manifests for the parent to stuff into
`global_data[f"probe-{probe_id}"]["attitude"]`.

A probe referenced by several missions (Cassini appears under CASSINI and
HUYGENS) is claimed by the first mission in sorted order — probes' chunk
dirs are keyed by probe id, so two missions extracting the same probe
concurrently would clobber each other.

Attitude depends only on kernels (CK/FK/SCLK/LSK/PCK) and the wire format,
never on DB/wikidata — so each probe's `_attitude.meta.json` sidecar lets an
unchanged probe skip the (expensive) extraction and re-inject its cached
manifest. Chunks live at `v1/attitude/<probe>/`, outside `position/`, so
`remove_old_outputs` spares them for the skip to reuse.
"""

import json
import logging
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed
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
_ATTITUDE_CACHE_VERSION = 3
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
    jobs: list[tuple[str, str, dict, list[dict]]] = []
    claimed: set[int] = set()
    for index_path in sorted(MISSIONS_DIR.glob(f"*/{ATTITUDE_INDEX_NAME}")):
        mission_dir = index_path.parent
        mission = mission_dir.name
        try:
            index = json.loads(index_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("attitude index %s unreadable: %s", index_path, exc)
            continue

        matched = probes_by_mission.get(mission, [])
        if not matched:
            logger.info(
                "attitude: mission %s has kernels but no registry probe references it",
                mission,
            )
            continue

        kernel_stamps = _mission_kernel_stamps(mission_dir, index)
        probe_jobs = []
        for probe in matched:
            probe_id = probe["probe_id"]
            if probe_id in claimed:
                logger.info(
                    "attitude: probe %d already claimed by an earlier mission, "
                    "skipping under %s",
                    probe_id,
                    mission,
                )
                continue
            claimed.add(probe_id)
            job = _plan_probe(
                out_dir, probe, mission, index, kernel_stamps, global_data, summary
            )
            if job is not None:
                probe_jobs.append(job)
        if probe_jobs:
            jobs.append((mission, str(mission_dir), index, probe_jobs))

    _run_jobs(out_dir, jobs, global_data, summary)
    logger.info("attitude: wrote chunks for %d probes", len(summary))
    return summary


def _plan_probe(
    out_dir: Path,
    probe: dict,
    mission: str,
    index: dict,
    kernel_stamps: dict[str, dict | None],
    global_data: dict[str, dict],
    summary: dict[str, dict],
) -> dict | None:
    """Cache-check one probe: re-inject a cached manifest (returns None), or
    return the picklable extraction job for a worker."""
    probe_id = probe["probe_id"]
    sc_naif = next(
        src["naif_id"] for src in probe["kernel_sources"] if src["mission"] == mission
    )
    bus_instr_id = sc_naif * 1000
    probe_out_dir = out_dir / "attitude" / str(probe_id)
    signature = {
        "version": _ATTITUDE_CACHE_VERSION,
        "frame": index["frame_name"],
        "bus_instr_id": bus_instr_id,
        "eps_deg": DEFAULT_EPS_DEG,
        "kernels": kernel_stamps,
    }

    hit, manifest = _read_cache(
        mirror_path(probe_out_dir / _ATTITUDE_META_NAME), signature, probe_out_dir
    )
    if not hit:
        return {
            "probe_id": probe_id,
            "bus_instr_id": bus_instr_id,
            "signature": signature,
        }
    if manifest is not None:
        _inject_manifest(probe_id, manifest, global_data)
        summary[str(probe_id)] = _summary_entry(mission, manifest, cached=True)
    else:
        logger.info(
            "attitude: probe %d (mission %s) unchanged, no keyframes (cached)",
            probe_id,
            mission,
        )
    return None


def _run_jobs(
    out_dir: Path,
    jobs: list[tuple[str, str, dict, list[dict]]],
    global_data: dict[str, dict],
    summary: dict[str, dict],
) -> None:
    """Fan mission extraction jobs out to worker processes and apply results."""
    if not jobs:
        return
    n_workers = min(len(jobs), max(1, min(12, multiprocessing.cpu_count() // 2)))
    logger.info(
        "attitude: extracting %d probes across %d missions on %d workers",
        sum(len(pj) for _, _, _, pj in jobs),
        len(jobs),
        n_workers,
    )
    with ProcessPoolExecutor(max_workers=n_workers) as ex:
        futures = {
            ex.submit(_extract_mission, str(out_dir), mdir, index, pjobs): mission
            for mission, mdir, index, pjobs in jobs
        }
        for fut in as_completed(futures):
            mission = futures[fut]
            try:
                results = fut.result()
            except Exception:
                logger.exception("attitude: mission %s worker crashed", mission)
                continue
            for res in results:
                _apply_result(mission, res, global_data, summary)


def _apply_result(
    mission: str, res: dict, global_data: dict[str, dict], summary: dict[str, dict]
) -> None:
    probe_id = res["probe_id"]
    if res["error"] is not None:
        logger.warning(
            "attitude: extraction failed for probe %s (mission %s): %s",
            probe_id,
            mission,
            res["error"],
        )
    elif res["manifest"] is None:
        logger.info(
            "attitude: no keyframes for probe %d (mission %s)", probe_id, mission
        )
    else:
        _inject_manifest(probe_id, res["manifest"], global_data)
        summary[str(probe_id)] = _summary_entry(mission, res["manifest"], cached=False)


def _extract_mission(
    out_dir_s: str, mission_dir_s: str, index: dict, probe_jobs: list[dict]
) -> list[dict]:
    """Worker-process entrypoint: furnish the mission once, extract every
    planned probe, write chunks + sidecars. Returns one result dict per probe
    (`manifest` None for an empty extraction, `error` set on failure)."""
    out_dir = Path(out_dir_s)
    mission_dir = Path(mission_dir_s)
    try:
        try:
            _furnish_mission(mission_dir, index)
        except spiceypy.exceptions.SpiceyError as exc:
            return [
                {
                    "probe_id": j["probe_id"],
                    "manifest": None,
                    "error": f"furnish failed: {exc}",
                }
                for j in probe_jobs
            ]
        ck_paths = [str(mission_dir / name) for name in index["ck_files"]]
        return [
            _extract_probe(out_dir, index["frame_name"], ck_paths, job)
            for job in probe_jobs
        ]
    finally:
        spiceypy.kclear()


def _extract_probe(
    out_dir: Path, frame_name: str, ck_paths: list[str], job: dict
) -> dict:
    probe_id = job["probe_id"]
    probe_out_dir = out_dir / "attitude" / str(probe_id)
    try:
        result = extract_attitude(
            probe_out_dir, ck_paths, job["bus_instr_id"], frame_name
        )
    except Exception as exc:
        # Don't let one probe's extraction abort the mission's batch — report
        # and continue. CK / FK / frame mismatches are the most likely cause
        # and are easier to diagnose probe-by-probe.
        return {"probe_id": probe_id, "manifest": None, "error": str(exc)}
    manifest = (
        manifest_entry(result, frame_name=frame_name) if result.n_keyframes else None
    )
    write_sidecar(
        mirror_path(probe_out_dir / _ATTITUDE_META_NAME),
        {"signature": job["signature"], "manifest": manifest},
    )
    return {"probe_id": probe_id, "manifest": manifest, "error": None}


def _furnish_mission(mission_dir: Path, index: dict) -> None:
    """Furnish LSK + PCK + every CK / FK / SCLK named in the index."""
    spiceypy.kclear()
    spiceypy.furnsh(str(_LSK))
    spiceypy.furnsh(str(_PCK))
    spiceypy.furnsh(str(mission_dir / index["fk"]))
    spiceypy.furnsh(str(mission_dir / index["sclk"]))
    for ck_name in index["ck_files"]:
        spiceypy.furnsh(str(mission_dir / ck_name))


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
