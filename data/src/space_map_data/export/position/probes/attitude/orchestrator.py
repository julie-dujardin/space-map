"""Probe attitude for the export: extract the changed shards, write chunks.

The pipeline calls `write_attitude` between `write_probes` and
`write_object_bundles`. For each mission with an `_attitude_index.json`:
1. Read the SEGMENT-level coverage of each CK, from the cache or a worker.
   A mission whose CK segments are relative to a frame that needs positions
   also furnishes its own SPKs everywhere after this.
2. Plan the spin of each probe, keyed on its full kernel signature. Only a
   spinner (Juno, HUYGENS) gets more than one span.
3. Extract the 7-day shards whose signature changed (`shards.py`), on one
   pool of workers across all missions, biggest task first.
4. Join the shards of each probe. Write its chunks only when a shard changed
   or a chunk is missing. Put the manifest in the probe's `__global__` entry.

Attitude depends only on kernels and the wire format, never on the DB. A
probe referenced by several missions (Cassini under CASSINI and HUYGENS)
belongs to the first mission in sorted order, because its chunk dir is keyed
by probe id. Chunks live at `v1/attitude/<probe>/`, outside `position/`, so
`remove_old_outputs` keeps them. The cache is in the metadata mirror
(`cache.py`).
"""

import json
import logging
import math
import multiprocessing
from collections.abc import Callable, MutableMapping
from concurrent.futures import (
    BrokenExecutor,
    Executor,
    Future,
    ProcessPoolExecutor,
    as_completed,
)
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from space_map_data.download.providers.spice.probes import MISSIONS_DIR
from space_map_data.download.providers.spice.probes.attitude.ck_kernels import (
    ATTITUDE_INDEX_NAME,
)
from space_map_data.export.position.probes.kernels import kernels_from_index
from space_map_data.export.sidecar_io import mirror_path
from space_map_data.probes.probe_id import load_registry
from space_map_data.utils.content_stamp import content_stamps
from space_map_data.utils.paths import DOWNLOAD_DIR, SOURCES_POSITION_DIR

from .adaptive import SEED_DT_S
from .baseline import SpinBaseline
from .cache import (
    CACHE_VERSION,
    COVERAGE_VERSION,
    SHARD_DIR,
    SPIN_VERSION,
    coverage_path,
    list_shards,
    load_coverage,
    load_probe_cache,
    load_shard,
    save_coverage,
    save_probe_cache,
    shard_name,
)
from .extractor import (
    ALIAS_ANGLE_RAD,
    DEFAULT_EPS_DEG,
    ExtractionResult,
    manifest_entry,
)
from .segments import (
    OMEGA_DDT,
    SpinSegment,
    is_spin_plan,
    is_spinner,
    spin_timeline_ets,
)
from .shards import (
    Coverage,
    Window,
    covering_cks,
    digest,
    join_shards,
    plan_shards,
    probe_instruments,
    probe_windows,
    segment_json,
    shard_signature,
    shard_spans,
    span_edges,
    split_runs,
)
from .worker import (
    ShardJob,
    ShardTask,
    ShardTaskResult,
    coverage_task,
    edge_task,
    fit_task,
    shard_task,
    timeline_task,
)
from .writer import write_chunks

logger = logging.getLogger(__name__)

_KERNELS_ROOT = SOURCES_POSITION_DIR / "spice-kernels"
_LSK = _KERNELS_ROOT / "lsk" / "naif0012.tls"
_PCK = _KERNELS_ROOT / "pck" / "pck00011.tpc"

_MAX_WORKERS = 12
_COVERAGE_BATCH = 64
# The CPU of one shard extraction, counted as NAS bytes for task sizes.
_SHARD_COST_BYTES = 16 << 20
# Several tasks per worker keep the tail of the pool short.
_TASKS_PER_WORKER = 4
_MIN_TASK_BYTES = 1 << 30


@dataclass
class _Probe:
    probe_id: int
    bus: int
    out_dir: Path
    meta_dir: Path
    cache: dict
    instruments: list[int] = field(default_factory=list)
    probe_sig: dict = field(default_factory=dict)
    full_sig: str = ""
    span: Window | None = None
    segments: list[SpinSegment] = field(default_factory=list)
    planned: dict[int, str] = field(default_factory=dict)
    pending: int = 0
    extracted: int = 0
    n_gaps: int = 0
    claimed_s: float = 0.0
    kept_s: float = 0.0
    error: str | None = None

    @property
    def spinner(self) -> bool:
        return is_spin_plan(self.segments)


@dataclass
class _Mission:
    name: str
    mission_dir: Path
    frame: str
    base: list[str]
    base_stamps: list[list]
    ck_names: list[str]
    ck_stamps: dict[str, dict | None]
    ck_sizes: dict[str, int]
    probes: list[_Probe]
    coverage: Coverage = field(default_factory=dict)
    error: str | None = None

    def ck_paths(self, names: list[str]) -> list[str]:
        return [str(self.mission_dir / name) for name in names]

    def live_probes(self) -> list[_Probe]:
        return [] if self.error else [p for p in self.probes if p.error is None]


class _NeedsScan(Exception):
    """A span edge lies in a long window, so SPICE must scan it."""


def _no_scan(start: float, end: float, forward: bool) -> float | None:
    raise _NeedsScan


def write_attitude(
    out_dir: Path, global_data: MutableMapping[str, dict]
) -> dict[str, dict]:
    """Extract attitude for every mission with kernels on disk; mutate
    `global_data` to add the manifest entry per probe.

    Returns `{probe_id: result_summary}`. Empty dict if no attitude kernels
    are present, so the pipeline runs fine without CK downloads in dev.
    """
    if not MISSIONS_DIR.exists():
        return {}
    missions = _load_missions(out_dir)
    summary: dict[str, dict] = {}
    n_workers = max(1, min(_MAX_WORKERS, multiprocessing.cpu_count() // 2))
    with ProcessPoolExecutor(max_workers=n_workers) as ex:
        run = _Run(out_dir, ex, n_workers)
        run.read_coverage(missions)
        run.plan_spins(missions)
        run.extract(missions, global_data, summary)
    logger.info("attitude: wrote chunks for %d probes", len(summary))
    return summary


def _load_missions(out_dir: Path) -> list[_Mission]:
    registry = load_registry()
    probes_by_mission: dict[str, list[dict]] = {}
    for entry in registry:
        for src in entry["kernel_sources"]:
            probes_by_mission.setdefault(src["mission"], []).append(entry)

    missions: list[_Mission] = []
    claimed: set[int] = set()
    for index_path in sorted(MISSIONS_DIR.glob(f"*/{ATTITUDE_INDEX_NAME}")):
        mission_dir = index_path.parent
        name = mission_dir.name
        matched = probes_by_mission.get(name, [])
        if not matched:
            logger.info(
                "attitude: mission %s has kernels but no registry probe references it",
                name,
            )
            continue
        entries: list[dict] = []
        for entry in matched:
            probe_id = entry["probe_id"]
            if probe_id in claimed:
                logger.info(
                    "attitude: probe %d already claimed by an earlier mission, "
                    "skipping under %s",
                    probe_id,
                    name,
                )
                continue
            claimed.add(probe_id)
            entries.append(entry)
        # The probes stay claimed when the index is unreadable. Otherwise a
        # later mission extracts them from its own CKs and prunes their shards.
        try:
            index = json.loads(index_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("attitude index %s unreadable: %s", index_path, exc)
            continue
        probes: list[_Probe] = []
        for entry in entries:
            probe_id = entry["probe_id"]
            naif = next(
                src["naif_id"]
                for src in entry["kernel_sources"]
                if src["mission"] == name
            )
            probe_out = out_dir / "attitude" / str(probe_id)
            meta_dir = mirror_path(probe_out)
            probes.append(
                _Probe(
                    probe_id=probe_id,
                    bus=naif * 1000,
                    out_dir=probe_out,
                    meta_dir=meta_dir,
                    cache=load_probe_cache(meta_dir),
                )
            )
        if not probes:
            continue
        base = [_LSK, _PCK, mission_dir / index["fk"], mission_dir / index["sclk"]]
        cks = [mission_dir / ck for ck in index["ck_files"]]
        stamps = content_stamps(base + cks)
        mission = _Mission(
            name=name,
            mission_dir=mission_dir,
            frame=index["frame_name"],
            base=[str(p) for p in base],
            base_stamps=[[_rel_key(p), stamps[p]] for p in base],
            ck_names=list(index["ck_files"]),
            ck_stamps={p.name: stamps[p] for p in cks},
            ck_sizes={p.name: (stamps[p] or {}).get("size", 0) for p in cks},
            probes=probes,
        )
        missing = [p.name for p in base + cks if stamps[p] is None]
        if missing:
            mission.error = f"missing kernels: {', '.join(missing[:3])}"
        missions.append(mission)
    return missions


def _add_ephemerides(m: _Mission) -> None:
    """Add the mission's own SPKs to its base kernels, for CK segments that
    are relative to a frame that needs positions."""
    try:
        spks = kernels_from_index(m.mission_dir)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("attitude: SPK index of %s unreadable: %s", m.name, exc)
        m.error = "SPK index unreadable"
        return
    if not spks:
        logger.warning(
            "attitude: %s has CK segments that need positions but no SPKs", m.name
        )
        return
    stamps = content_stamps(spks)
    missing = [p.name for p in spks if stamps[p] is None]
    if missing:
        m.error = f"missing kernels: {', '.join(missing[:3])}"
        return
    logger.info(
        "attitude: %s has CK segments that need positions; furnishing %d SPKs",
        m.name,
        len(spks),
    )
    m.base += [str(p) for p in spks]
    m.base_stamps += [[_rel_key(p), stamps[p]] for p in spks]


def _rel_key(path: Path) -> str:
    try:
        return str(path.relative_to(DOWNLOAD_DIR))
    except ValueError:
        return str(path)


class _Run:
    def __init__(self, out_dir: Path, ex: Executor, n_workers: int) -> None:
        self.out_dir = out_dir
        self.ex = ex
        self.n_workers = n_workers

    def _submit(self, fn: Callable, *args) -> Future:
        """`ex.submit`, or a failed future when the pool is broken."""
        try:
            return self.ex.submit(fn, *args)
        except BrokenExecutor as exc:
            future: Future = Future()
            future.set_exception(exc)
            return future

    def _gather(self, calls: list[tuple[Callable, tuple]]) -> list:
        """Run `calls` on the pool. Each result is the value or the exception."""
        futures = [self._submit(fn, *args) for fn, args in calls]
        out: list = []
        for future in futures:
            try:
                out.append(future.result())
            except Exception as exc:
                out.append(exc)
        return out

    def read_coverage(self, missions: list[_Mission]) -> None:
        """Fill `mission.coverage`. Only CKs with a new stamp are read.

        A CK that fails to read fails its mission for this run. Partial
        coverage would plan too few shards and prune good ones.
        """
        attitude_meta = mirror_path(self.out_dir / "attitude")
        calls: list[tuple[Callable, tuple]] = []
        owners: list[_Mission] = []
        entries: dict[str, dict[str, dict]] = {}
        dirty: set[str] = set()
        for m in missions:
            if m.error:
                continue
            key = self._coverage_key(m)
            cached = load_coverage(coverage_path(attitude_meta, m.name), key)
            kept = {
                name: cached[name]
                for name in m.ck_names
                if name in cached and cached[name]["stamp"] == m.ck_stamps[name]
            }
            entries[m.name] = kept
            missing = [name for name in m.ck_names if name not in kept]
            if missing or set(cached) != set(kept):
                dirty.add(m.name)
            for i in range(0, len(missing), _COVERAGE_BATCH):
                batch = missing[i : i + _COVERAGE_BATCH]
                calls.append((coverage_task, (m.base, m.ck_paths(batch))))
                owners.append(m)
        if calls:
            logger.info(
                "attitude: reading the coverage of %d CKs",
                sum(len(args[1]) for _, args in calls),
            )
        for m, res in zip(owners, self._gather(calls), strict=True):
            if isinstance(res, Exception):
                logger.error("attitude: coverage read failed for %s: %r", m.name, res)
                m.error = "coverage read failed"
                continue
            for path, read in res.items():
                name = Path(path).name
                if isinstance(read, str):
                    logger.error("attitude: ckcov failed for %s: %s", path, read)
                    m.error = "coverage read failed"
                    continue
                entries[m.name][name] = {
                    "stamp": m.ck_stamps[name],
                    "cover": {
                        str(i): [list(w) for w in ws] for i, ws in read["cover"].items()
                    },
                    "ephemeris": read["ephemeris"],
                }
        for m in missions:
            if m.name not in entries:
                continue
            kept = entries[m.name]
            if m.name in dirty:
                save_coverage(
                    coverage_path(attitude_meta, m.name), self._coverage_key(m), kept
                )
            if m.error:
                continue
            m.coverage = {
                name: {
                    int(i): [(w[0], w[1]) for w in ws]
                    for i, ws in kept[name]["cover"].items()
                }
                for name in m.ck_names
            }
            if any(kept[name]["ephemeris"] for name in m.ck_names):
                _add_ephemerides(m)

    @staticmethod
    def _coverage_key(m: _Mission) -> dict:
        # TDB coverage depends on the LSK, the SCLK and the clock map in the FK.
        return {
            "version": COVERAGE_VERSION,
            "lsk": m.base_stamps[0][1],
            "fk": m.base_stamps[2][1],
            "sclk": m.base_stamps[3][1],
        }

    def plan_spins(self, missions: list[_Mission]) -> None:
        """Set each probe's span and spin segments, from the cache or the pool."""
        todo: list[tuple[_Mission, _Probe]] = []
        edge_calls: list[tuple[Callable, tuple]] = []
        edge_probes: list[_Probe] = []
        for m in missions:
            for p in m.live_probes():
                p.instruments = probe_instruments(m.coverage, p.bus)
                p.probe_sig = {
                    "version": CACHE_VERSION,
                    "frame": m.frame,
                    "bus": p.bus,
                    "instruments": p.instruments,
                    "eps": DEFAULT_EPS_DEG,
                    "kernels": m.base_stamps,
                }
                p.full_sig = digest(
                    {
                        "probe": p.probe_sig,
                        "cks": [[n, m.ck_stamps[n]] for n in m.ck_names],
                        "spin": SPIN_VERSION,
                    }
                )
                spin = p.cache.get("spin")
                if spin is not None and spin["sig"] == p.full_sig:
                    p.span = (
                        (spin["span"][0], spin["span"][1]) if spin["span"] else None
                    )
                    p.segments = [_segment_from_json(s) for s in spin["segments"]]
                    continue
                todo.append((m, p))
                windows = probe_windows(m.coverage, m.ck_names, p.instruments)
                try:
                    p.span = span_edges(windows, _no_scan)
                except _NeedsScan:
                    edge_calls.append(
                        (edge_task, (m.base, m.ck_paths(m.ck_names), m.frame, windows))
                    )
                    edge_probes.append(p)
        if not todo:
            return
        logger.info("attitude: planning the spin of %d probes", len(todo))
        for p, res in zip(edge_probes, self._gather(edge_calls), strict=True):
            if isinstance(res, Exception):
                p.error = f"span scan failed: {res!r}"
            else:
                p.span = res

        timeline_calls: list[tuple[Callable, tuple]] = []
        chunks: list[tuple[_Probe, np.ndarray]] = []
        for m, p in todo:
            if p.error or p.span is None:
                continue
            ets = spin_timeline_ets(*p.span)
            # A short span has fewer probes than workers.
            for part in np.array_split(ets, min(self.n_workers, ets.size)):
                cks = covering_cks(
                    m.coverage, m.ck_names, float(part[0]), float(part[-1]) + OMEGA_DDT
                )
                timeline_calls.append(
                    (timeline_task, (m.base, m.ck_paths(cks), m.frame, part))
                )
                chunks.append((p, part))
        omegas: dict[int, list] = {}
        for (p, _), res in zip(chunks, self._gather(timeline_calls), strict=True):
            if isinstance(res, Exception):
                p.error = f"spin timeline failed: {res!r}"
            else:
                omegas.setdefault(p.probe_id, []).extend(res)

        fit_calls: list[tuple[Callable, tuple]] = []
        fit_probes: list[_Probe] = []
        for m, p in todo:
            if p.error:
                continue
            if p.span is None:
                p.segments = []
                continue
            om = omegas[p.probe_id]
            if not is_spinner(om, alias_angle=ALIAS_ANGLE_RAD, seed_dt=SEED_DT_S):
                p.segments = [SpinSegment(p.span[0], p.span[1], None)]
                continue
            fit_calls.append(
                (
                    fit_task,
                    (
                        m.base,
                        m.ck_paths(m.ck_names),
                        m.frame,
                        p.span,
                        spin_timeline_ets(*p.span),
                        om,
                        ALIAS_ANGLE_RAD,
                        SEED_DT_S,
                    ),
                )
            )
            fit_probes.append(p)
        for p, res in zip(fit_probes, self._gather(fit_calls), strict=True):
            if isinstance(res, Exception):
                p.error = f"spin fit failed: {res!r}"
            else:
                p.segments = res

        for m, p in todo:
            if p.error:
                continue
            if p.spinner:
                logger.info(
                    "attitude: probe %d spins: %d spans at %s RPM",
                    p.probe_id,
                    len(p.segments),
                    ", ".join(_rpm(s) for s in p.segments),
                )
                if p.cache.get("spin") is not None:
                    logger.info(
                        "attitude: probe %d has a new spin plan. Each shard in a "
                        "span that changed extracts again.",
                        p.probe_id,
                    )
            p.cache["spin"] = {
                "sig": p.full_sig,
                "span": list(p.span) if p.span else None,
                "segments": [segment_json(s) for s in p.segments],
            }
            save_probe_cache(p.meta_dir, p.cache)

    def extract(
        self,
        missions: list[_Mission],
        global_data: MutableMapping[str, dict],
        summary: dict[str, dict],
    ) -> None:
        """Extract the stale shards, then finalize each probe when its last
        shard is in."""
        tasks: list[tuple[float, ShardTask, _Mission]] = []
        for m in missions:
            tasks += self._mission_tasks(m)
        total = sum(cost for cost, _, _ in tasks)
        target = max(_MIN_TASK_BYTES, total / (self.n_workers * _TASKS_PER_WORKER))
        tasks = [sub for cost, task, m in tasks for sub in self._split(task, m, target)]
        tasks.sort(key=lambda t: t[0], reverse=True)
        if tasks:
            logger.info(
                "attitude: extracting %d shards in %d tasks on %d workers",
                sum(len(js) for _, t, _ in tasks for js in t.jobs.values()),
                len(tasks),
                self.n_workers,
            )
        futures: dict[Future[ShardTaskResult], tuple[ShardTask, _Mission]] = {
            self._submit(shard_task, task): (task, m) for _, task, m in tasks
        }
        for m in missions:
            for p in m.probes:
                if p.pending == 0:
                    _finalize(m, p, global_data, summary)

        bytes_read = 0
        for future in as_completed(futures):
            task, m = futures[future]
            by_id = {p.probe_id: p for p in m.probes}
            touched: set[int] = set()
            try:
                result = future.result()
            except Exception as exc:
                logger.error("attitude: mission %s task crashed: %r", m.name, exc)
                for jobs in task.jobs.values():
                    for job in jobs:
                        p = by_id[job.probe_id]
                        p.pending -= 1
                        p.error = p.error or f"worker crashed: {exc!r}"
                        touched.add(p.probe_id)
            else:
                bytes_read += result.bytes_read
                for r in result.results:
                    p = by_id[r.probe_id]
                    p.pending -= 1
                    touched.add(p.probe_id)
                    if r.error is not None:
                        p.error = p.error or f"shard {r.k}: {r.error}"
                        continue
                    p.extracted += 1
                    p.n_gaps += r.n_gaps
                    p.claimed_s += r.claimed_s
                    p.kept_s += r.kept_s
            for probe_id in touched:
                if by_id[probe_id].pending == 0:
                    _finalize(m, by_id[probe_id], global_data, summary)
        if tasks:
            logger.info("attitude: read %.1f GB of CKs", bytes_read / 1e9)

    def _mission_tasks(self, m: _Mission) -> list[tuple[float, ShardTask, _Mission]]:
        """Plan each probe's shards and group the stale ones of the mission
        into one task per run of consecutive shards."""
        jobs: dict[int, list[ShardJob]] = {}
        cks_by_k: dict[int, set[str]] = {}
        for p in m.live_probes():
            if p.span is None:
                continue
            plan = plan_shards(m.coverage, m.ck_names, p.instruments, p.span)
            have = list_shards(p.meta_dir)
            segments = p.segments if p.spinner else None
            for k, names in plan.items():
                spans = shard_spans(k, segments)
                sig = shard_signature(
                    p.probe_sig,
                    [[n, m.ck_stamps[n]] for n in names],
                    None if segments is None else spans,
                )
                p.planned[k] = sig
                if shard_name(k, sig) in have:
                    continue
                jobs.setdefault(k, []).append(
                    ShardJob(
                        probe_id=p.probe_id,
                        k=k,
                        frame=m.frame,
                        instruments=p.instruments,
                        ck_paths=m.ck_paths(names),
                        spans=spans,
                        out_path=str(p.meta_dir / SHARD_DIR / shard_name(k, sig)),
                    )
                )
                cks_by_k.setdefault(k, set()).update(names)
                p.pending += 1
        if not jobs:
            return []
        order = {name: i for i, name in enumerate(m.ck_names)}
        names_by_k = {k: sorted(v, key=order.__getitem__) for k, v in cks_by_k.items()}
        out: list[tuple[float, ShardTask, _Mission]] = []
        for run in split_runs(sorted(jobs), lambda k: 0.0, math.inf):
            names = sorted(
                {n for k in run for n in names_by_k[k]}, key=order.__getitem__
            )
            task = ShardTask(
                base=m.base,
                ck_paths=m.ck_paths(names),
                shards=[(k, m.ck_paths(names_by_k[k])) for k in run],
                jobs={k: jobs[k] for k in run},
            )
            out.append((self._task_cost(task, m), task, m))
        return out

    def _split(
        self, task: ShardTask, m: _Mission, target: float
    ) -> list[tuple[float, ShardTask, _Mission]]:
        """Cut a run into tasks of about `target` cost."""
        costs = self._shard_costs(task, m)
        runs = split_runs([k for k, _ in task.shards], costs.__getitem__, target)
        paths_by_k = dict(task.shards)
        order = {path: i for i, path in enumerate(task.ck_paths)}
        out = []
        for run in runs:
            paths = sorted(
                {p for k in run for p in paths_by_k[k]}, key=order.__getitem__
            )
            sub = ShardTask(
                base=task.base,
                ck_paths=paths,
                shards=[(k, paths_by_k[k]) for k in run],
                jobs={k: task.jobs[k] for k in run},
            )
            out.append((self._task_cost(sub, m), sub, m))
        return out

    def _task_cost(self, task: ShardTask, m: _Mission) -> float:
        return sum(self._shard_costs(task, m).values())

    @staticmethod
    def _shard_costs(task: ShardTask, m: _Mission) -> dict[int, float]:
        """NAS bytes of the CKs each shard adds to the previous one, plus CPU."""
        costs: dict[int, float] = {}
        previous: set[str] = set()
        for k, paths in task.shards:
            new = [p for p in paths if p not in previous]
            costs[k] = sum(
                m.ck_sizes[Path(p).name] for p in new
            ) + _SHARD_COST_BYTES * len(task.jobs[k])
            previous = set(paths)
        return costs


def _finalize(
    m: _Mission,
    p: _Probe,
    global_data: MutableMapping[str, dict],
    summary: dict[str, dict],
) -> None:
    """Write the probe's chunks when its shards changed, then inject its
    manifest and drop the shard files it no longer uses."""
    error = m.error or p.error
    if error is not None:
        logger.warning(
            "attitude: extraction failed for probe %s (mission %s): %s",
            p.probe_id,
            m.name,
            error,
        )
        return
    try:
        manifest, cached = _settle_output(m, p)
    except Exception:
        logger.exception(
            "attitude: chunk write failed for probe %d (mission %s)",
            p.probe_id,
            m.name,
        )
        return

    if p.extracted:
        logger.info(
            "attitude: probe %d (%s): extracted %d of %d shards",
            p.probe_id,
            m.name,
            p.extracted,
            len(p.planned),
        )
    if p.n_gaps:
        logger.warning(
            "attitude: %s — %d gap probe(s) hit CK coverage holes (repeated last good)",
            m.frame,
            p.n_gaps,
        )
    if p.claimed_s:
        logger.warning(
            "attitude: %s — CK windows claim %.1f d but only %.1f d resolve; "
            "shrunk to the valid runs",
            m.frame,
            p.claimed_s / 86400.0,
            p.kept_s / 86400.0,
        )
    if manifest is None:
        logger.info(
            "attitude: no keyframes for probe %d (mission %s)", p.probe_id, m.name
        )
        return
    _inject_manifest(p.probe_id, manifest, global_data)
    summary[str(p.probe_id)] = _summary_entry(
        m.name, manifest, cached=cached and not p.extracted
    )


def _settle_output(m: _Mission, p: _Probe) -> tuple[dict | None, bool]:
    """The probe's manifest, and True when it comes from the cache.

    The chunks are written again when a planned shard changed or a chunk is
    missing. Then the shard files that no planned shard uses are deleted.
    """
    planned = sorted(p.planned.items())
    output_sig = digest(
        {
            "spin": [segment_json(s) for s in p.segments] if p.spinner else None,
            "shards": planned,
        }
    )
    output = p.cache.get("output")
    cached = (
        output is not None
        and output["sig"] == output_sig
        and _chunks_present(p, output)
    )
    if cached:
        manifest = output["manifest"]
    else:
        manifest = _write_output(m, p, planned)
        p.cache["output"] = {"sig": output_sig, "manifest": manifest}
    _prune_shards(p, {shard_name(k, sig) for k, sig in planned})
    save_probe_cache(p.meta_dir, p.cache)
    return manifest, cached


def _write_output(
    m: _Mission, p: _Probe, planned: list[tuple[int, str]]
) -> dict | None:
    """Join the planned shards and write the chunks. Returns the manifest, or
    None when there are no keyframes."""
    streams = join_shards(
        (_load_planned_shard(p, k, sig) for k, sig in planned),
        len(p.segments) if p.spinner else 1,
    )
    files = write_chunks(p.out_dir, streams)
    n_keyframes = sum(len(ets) for ets, _ in streams)
    if not n_keyframes:
        return None
    result = ExtractionResult(
        n_keyframes=n_keyframes,
        files=files,
        segments=p.segments,
        coverage_start_jd=files[0].start_jd,
        coverage_end_jd=files[-1].end_jd,
    )
    return manifest_entry(result, frame_name=m.frame)


def _load_planned_shard(
    p: _Probe, k: int, sig: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    path = p.meta_dir / SHARD_DIR / shard_name(k, sig)
    try:
        return load_shard(path)
    except Exception:
        # The next run extracts the shard again.
        path.unlink(missing_ok=True)
        raise


def _chunks_present(p: _Probe, output: dict) -> bool:
    manifest = output["manifest"]
    if manifest is None:
        return True
    return all((p.out_dir / f["name"]).exists() for f in manifest["files"])


def _prune_shards(p: _Probe, keep: set[str]) -> None:
    """Delete shard files that no planned shard uses, such as shards that no
    longer have a CK."""
    for name in list_shards(p.meta_dir) - keep:
        (p.meta_dir / SHARD_DIR / name).unlink(missing_ok=True)


def _rpm(seg: SpinSegment) -> str:
    if seg.baseline is None:
        return "raw"
    return f"{seg.baseline.rate_rad_s / (2 * math.pi) * 60:.1f}"


def _segment_from_json(data: dict) -> SpinSegment:
    b = data["baseline"]
    baseline = (
        None
        if b is None
        else SpinBaseline(
            axis=np.array(b["axis"]),
            rate_rad_s=b["rate"],
            anchor=np.array(b["anchor"]),
            t0=b["t0"],
        )
    )
    return SpinSegment(data["start"], data["end"], baseline, data["seed_dt"])


def _inject_manifest(
    probe_id: int, manifest: dict, global_data: MutableMapping[str, dict]
) -> None:
    """Merge the attitude manifest into the probe's `__global__` object entry."""
    object_key = f"probe-{probe_id}"
    if object_key not in global_data:
        # Excluded or filtered probes have no global entry. Do not make an
        # orphan entry for them.
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
