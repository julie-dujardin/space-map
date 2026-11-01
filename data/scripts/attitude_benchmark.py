"""Benchmark the exported probe-attitude chunks against SPICE truth.

Decodes the chunks an export wrote with the frontend's logic and compares them
with `pxform("J2000", frame)`. A uniform grid misses a brief fault, so each
probe is also sampled at its keyframes, between them, and where its stream
turns fastest. A keyframe at an instant SPICE cannot resolve has no source.

The frontend shows no attitude in a hole of the manifest, so those instants are
left out of the error figures. They are sampled apart: SPICE resolving one means
the hole hides data, and a keyframe deep in a hole has no source. The grid
spreads over the time outside the holes. Its samples with no data are gaps too
short to be holes, which the frontend interpolates across, or folds of a clock
kernel.

Run from data/:
    uv run python scripts/attitude_benchmark.py
    uv run python scripts/attitude_benchmark.py --missions GAIA MRO
    uv run python scripts/attitude_benchmark.py --samples 4000 --json out.json
    uv run python scripts/attitude_benchmark.py --out-dir <dir of a scratch run>
"""

import argparse
import datetime
import gzip
import json
import logging
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import spiceypy

from space_map_data.export.position.probes.attitude import orchestrator
from space_map_data.export.position.probes.attitude.adaptive import FINE_DT_S
from space_map_data.export.position.probes.attitude.baseline import (
    baseline_quaternion,
)
from space_map_data.export.position.probes.attitude.cache import (
    coverage_path,
    load_coverage,
)
from space_map_data.export.position.probes.attitude.extractor import POINT_WINDOW_S
from space_map_data.export.position.probes.attitude.format import (
    COMPONENT_SCALE,
    HEADER_SIZE,
    KEYFRAME_SIZE,
)
from space_map_data.export.position.probes.attitude.quaternion import (
    angle_between,
    q_mul,
    slerp,
)
from space_map_data.export.position.probes.attitude.sample import ck_windows
from space_map_data.export.position.probes.attitude.shards import (
    SHARD_S,
    plan_shards,
)
from space_map_data.export.position.probes.attitude.worker import _furnish
from space_map_data.export.sidecar_io import mirror_path
from space_map_data.utils.paths import EXPORT_DIR

J2000_JD = 2451545.0
S_PER_DAY = 86400.0
RAD2DEG = 180.0 / np.pi
# Above this a sample counts as wrong: the frontend's SLERP budget is 0.1°.
BAD_DEG = 1.0
# Keyframes this close bracket a jump in the CK, which has no value inside it. A
# float32 dt after a long interval rounds by milliseconds to tenths of a second,
# so a bracket decodes wider than it is, and a keyframe lands just off its data.
JUMP_S = 0.02
NEAR_S = (-FINE_DT_S, FINE_DT_S, -0.1, 0.1)
# Hole samples stay this far inside the edges, past what `truth_task` looks at.
HOLE_INSET_S = 2.0
# An instant whose SCLK ticks come back further off than this is on a fold of
# the clock kernel: SPICE resolves it, with the attitude of another time.
CLOCK_FOLD_S = 1.0


def iso(jd: float) -> str:
    return (
        datetime.datetime(2000, 1, 1, 12) + datetime.timedelta(days=jd - J2000_JD)
    ).strftime("%Y-%m-%d")


def decode_chunk(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """One chunk → `(jd[], quat[w, x, y, z][])`, mirroring `parseAttitudeChunk`."""
    buf = gzip.decompress(path.read_bytes())
    start_jd = np.frombuffer(buf, "<f8", 1, 8)[0]
    rows = np.frombuffer(buf, np.uint8, offset=HEADER_SIZE).reshape(-1, KEYFRAME_SIZE)
    n = rows.shape[0]
    dts = np.frombuffer(rows[:, :4].tobytes(), "<f4").astype(np.float64)
    dts[0] = 0.0
    times = start_jd + np.cumsum(dts) / S_PER_DAY
    idx = rows[:, 4]
    kept = np.frombuffer(rows[:, 5:].tobytes(), "<i2").reshape(n, 3) / COMPONENT_SCALE
    slots = np.ones((n, 4), dtype=bool)
    slots[np.arange(n), idx] = False
    quats = np.empty((n, 4))
    quats[slots] = kept.ravel()
    quats[~slots] = np.sqrt(np.maximum(0.0, 1.0 - (kept**2).sum(axis=1)))
    return times, quats


@dataclass
class Chunk:
    times: np.ndarray
    quats: np.ndarray
    baseline_index: int


def _file_index_for(starts: np.ndarray, jd: float) -> int:
    """Last file that starts at or before `jd`, clamped: `fileIndexFor`."""
    return max(0, int(np.searchsorted(starts, jd, side="right")) - 1)


def _sample_residual(jd: float, ci: int, chunks: list[Chunk]) -> np.ndarray:
    """SLERP the stream at `jd` in chunk `ci`, bridging to the next chunk only
    when it shares this chunk's span: `sampleChunk`."""
    chunk = chunks[ci]
    times, quats = chunk.times, chunk.quats
    if jd <= times[0]:
        return quats[0]
    if jd >= times[-1]:
        nxt = chunks[ci + 1] if ci + 1 < len(chunks) else None
        if (
            nxt is not None
            and nxt.baseline_index == chunk.baseline_index
            and nxt.times[0] > times[-1]
        ):
            span = nxt.times[0] - times[-1]
            return slerp(quats[-1], nxt.quats[0], min(1.0, (jd - times[-1]) / span))
        return quats[-1]
    hi = int(np.searchsorted(times, jd, side="right"))
    lo = hi - 1
    span = times[hi] - times[lo]
    return slerp(quats[lo], quats[hi], (jd - times[lo]) / span if span > 0 else 0.0)


def reconstruct(
    jd: float, manifest: dict, starts: np.ndarray, chunks: list[Chunk]
) -> np.ndarray:
    """Full J2000→body quaternion at `jd`: `orientationAt`."""
    ci = _file_index_for(starts, jd)
    resid = _sample_residual(jd, ci, chunks)
    if manifest["baselines"] is None:
        return resid
    b = manifest["baselines"][chunks[ci].baseline_index]
    t_s = (jd - b["anchor_jd"]) * S_PER_DAY
    spin = baseline_quaternion(np.array(b["axis"]), b["rate_rad_s"], t_s)
    return q_mul(q_mul(spin, np.array(b["anchor"])), resid)


def in_holes(jds: np.ndarray, holes: list[list[float]]) -> np.ndarray:
    """True for each of `jds` strictly inside a hole: `inHole`."""
    inside = np.zeros(jds.size, dtype=bool)
    if holes:
        table = np.array(holes)
        i = np.searchsorted(table[:, 1], jds, side="right")
        some = i < len(table)
        inside[some] = table[i[some], 0] < jds[some]
    return inside


def hole_jds(holes: list[list[float]], n: int, rng: np.random.Generator) -> np.ndarray:
    """Instants inside the holes: just inside each edge, and `n` at random,
    more of them in a long hole."""
    if not holes:
        return np.empty(0)
    table = np.array(holes)
    days = table[:, 1] - table[:, 0]
    inset = HOLE_INSET_S / S_PER_DAY
    at = rng.choice(len(table), n, p=days / days.sum())
    random = rng.uniform(table[at, 0] + inset, table[at, 1] - inset)
    return np.concatenate([table[:, 0] + inset, table[:, 1] - inset, random])


def grid_jds(start: float, end: float, holes: list[list[float]], n: int) -> np.ndarray:
    """`n` instants spread evenly over the time outside the holes."""
    table = np.array(holes).reshape(-1, 2)
    starts = np.concatenate([[start], table[:, 1]])
    ends = np.concatenate([table[:, 0], [end]])
    total = np.cumsum(ends - starts)
    at = np.linspace(0.0, total[-1], n)
    i = np.searchsorted(total, at)
    return ends[i] - (total[i] - at)


def sample_jds(
    chunks: list[Chunk], manifest: dict, n: int, rng: np.random.Generator
) -> dict[str, np.ndarray]:
    """The sample instants of one probe that have attitude, per set."""
    times = np.concatenate([c.times for c in chunks])
    quats = np.concatenate([c.quats for c in chunks])
    pair = np.flatnonzero(np.diff(times) * S_PER_DAY > JUMP_S)
    # A pair across a hole is no motion: the SLERP there never runs.
    pair = pair[~in_holes((times[pair] + times[pair + 1]) / 2.0, manifest["holes"])]
    dots = np.abs(np.sum(quats[pair] * quats[pair + 1], axis=1))
    rate = 2.0 * np.arccos(np.minimum(1.0, dots)) / (times[pair + 1] - times[pair])
    fastest = pair[np.argsort(rate)[-n:]]
    picks = rng.choice(pair, min(n, pair.size), replace=False) if pair.size else pair
    sets = {
        "grid": grid_jds(
            manifest["start_jd"], manifest["end_jd"], manifest["holes"], n
        ),
        "keyframes": times[rng.choice(times.size, min(n, times.size), replace=False)],
        "midpoints": (times[picks] + times[picks + 1]) / 2.0,
        "fastest": np.concatenate(
            [times[fastest], (times[fastest] + times[fastest + 1]) / 2.0]
        ),
        "hole_edges": np.array(manifest["holes"]).ravel(),
    }
    return {k: v[~in_holes(v, manifest["holes"])] for k, v in sets.items()}


@dataclass(frozen=True)
class TruthTask:
    frame: str
    kernels: list[str]
    ck_paths: list[str]
    instruments: list[int]
    ets: np.ndarray


def on_clock_fold(clock: int, et: float) -> bool:
    """True when the SCLK ticks of `et` do not come back to it, or it has none."""
    try:
        return abs(spiceypy.sct2e(clock, spiceypy.sce2c(clock, et)) - et) > CLOCK_FOLD_S
    except spiceypy.exceptions.SpiceyError:
        return True


def truth_task(task: TruthTask) -> np.ndarray:
    """`pxform` quaternions at `task.ets`; NaN where SPICE cannot resolve, or
    resolves with the attitude of another time.

    A JD cannot hold the exact time of a keyframe at an edge of a CK's data, or
    of a lone CK record, so the data next to an instant stands for it.
    """

    def truth(et: float) -> np.ndarray | None:
        if on_clock_fold(clock, et):
            return None
        for at in (et, *(et + d for d in NEAR_S)):
            try:
                return spiceypy.m2q(spiceypy.pxform("J2000", task.frame, at))
            except spiceypy.exceptions.SpiceyError:
                pass
        return None

    out = np.full((task.ets.size, 4), np.nan)
    _furnish(task.kernels)
    try:
        clock = spiceypy.ckmeta(task.instruments[0], "SCLK")
        missed = []
        for i, et in enumerate(task.ets.tolist()):
            q = truth(et)
            if q is None:
                missed.append(i)
            else:
                out[i] = q
        if missed:
            windows = [
                w for i in task.instruments for w in ck_windows(task.ck_paths, i)
            ]
            records = np.array(sorted(a for a, b in windows if b - a <= POINT_WINDOW_S))
            if records.size:
                for i in missed:
                    k = int(np.abs(records - task.ets[i]).argmin())
                    if abs(records[k] - task.ets[i]) <= POINT_WINDOW_S:
                        q = truth(float(records[k]))
                        if q is not None:
                            out[i] = q
    finally:
        spiceypy.kclear()
    return out


def truth_at(
    ex: ProcessPoolExecutor,
    craft,
    plan: dict[int, list[str]],
    instruments: list[int],
    ets: np.ndarray,
) -> np.ndarray:
    """Truth at `ets`, one task per shard with the CKs that shard furnishes."""
    out = np.full((ets.size, 4), np.nan)
    shards = np.floor(ets / SHARD_S).astype(np.int64)
    calls = []
    for k in np.unique(shards):
        names = plan.get(int(k))
        if names:
            at = np.flatnonzero(shards == k)
            kernels = craft.base + craft.ck_paths(names)
            task = TruthTask(
                craft.frame, kernels, craft.ck_paths(names), instruments, ets[at]
            )
            calls.append((at, ex.submit(truth_task, task)))
    for at, future in calls:
        out[at] = future.result()
    return out


@dataclass
class Row:
    probe: int
    mission: str
    manifest: dict
    n_chunks: int = 0
    total_kb: float = 0.0
    max_kb: float = 0.0
    drift_s: float = 0.0
    err: dict[str, np.ndarray] = field(default_factory=dict)
    worst: list = field(default_factory=list)
    no_truth: dict[str, int] = field(default_factory=dict)
    n_hole_samples: int = 0
    hidden: int = 0
    keyframes_in_holes: int = 0
    seconds: float = 0.0


def coverage_of(root: Path, craft) -> tuple[dict, bool]:
    """The export's coverage cache: `(coverage, any CK needs positions)`."""
    path = coverage_path(mirror_path(root / "attitude"), craft.frame)
    cks = load_coverage(path, orchestrator._Run._coverage_key(craft))
    if not cks:
        raise LookupError(f"no coverage cache for these kernels at {path}")
    coverage = {
        name: {
            int(i): [tuple(w) for w in windows]
            for i, windows in cks[name]["cover"].items()
        }
        for name in craft.ck_names
    }
    return coverage, any(cks[n]["ephemeris"] for n in craft.ck_names)


def bench_probe(ex, root: Path, craft, probe, n: int) -> Row | None:
    manifest = (probe.cache.get("output") or {}).get("manifest")
    if not manifest:
        return None
    t0 = time.time()
    row = Row(probe.probe_id, craft.mission, manifest)
    chunks: list[Chunk] = []
    sizes = []
    for f in manifest["files"]:
        path = probe.out_dir / f["name"]
        times, quats = decode_chunk(path)
        chunks.append(Chunk(times, quats, f.get("baseline_index", 0)))
        sizes.append(path.stat().st_size)
        row.drift_s = max(row.drift_s, abs(times[-1] - f["end_jd"]) * S_PER_DAY)
    row.n_chunks, row.total_kb, row.max_kb = (
        len(sizes),
        sum(sizes) / 1024,
        max(sizes) / 1024,
    )
    starts = np.array([f["start_jd"] for f in manifest["files"]])
    span = (
        (manifest["start_jd"] - J2000_JD) * S_PER_DAY,
        (manifest["end_jd"] - J2000_JD) * S_PER_DAY,
    )
    plan = plan_shards(craft.coverage, craft.ck_names, probe.instruments, span)
    rng = np.random.default_rng(probe.probe_id)
    sets = sample_jds(chunks, manifest, n, rng)
    in_hole = hole_jds(manifest["holes"], n, rng)
    all_jds = np.concatenate([*sets.values(), in_hole])
    all_truth = truth_at(
        ex, craft, plan, probe.instruments, (all_jds - J2000_JD) * S_PER_DAY
    )
    cuts = np.cumsum([jds.size for jds in sets.values()])
    row.n_hole_samples = in_hole.size
    row.hidden = int((~np.isnan(all_truth[cuts[-1] :, 0])).sum())
    inset = HOLE_INSET_S / S_PER_DAY
    deep = [[a + inset, b - inset] for a, b in manifest["holes"]]
    row.keyframes_in_holes = sum(int(in_holes(c.times, deep).sum()) for c in chunks)
    for (name, jds), truth in zip(
        sets.items(), np.split(all_truth, cuts)[:-1], strict=True
    ):
        known = ~np.isnan(truth[:, 0])
        row.no_truth[name] = int((~known).sum())
        errs = np.array(
            [
                angle_between(reconstruct(jd, manifest, starts, chunks), q) * RAD2DEG
                for jd, q in zip(jds[known], truth[known], strict=True)
            ]
        )
        row.err[name] = errs
        if errs.size:
            for i in np.argsort(errs)[-3:]:
                row.worst.append((float(errs[i]), name, float(jds[known][i])))
    row.worst.sort(reverse=True)
    row.seconds = time.time() - t0
    return row


def summary(row: Row) -> dict | None:
    errs = np.concatenate(list(row.err.values()))
    if not errs.size:
        return None
    m = row.manifest
    return {
        "probe": row.probe,
        "mission": row.mission,
        "start_jd": m["start_jd"],
        "end_jd": m["end_jd"],
        "n_spans": len(m["baselines"] or []),
        "n_keyframes": m["n_keyframes"],
        "n_chunks": row.n_chunks,
        "total_kb": row.total_kb,
        "max_chunk_kb": row.max_kb,
        "err_med_deg": float(np.median(errs)),
        "err_p95_deg": float(np.percentile(errs, 95)),
        "err_p999_deg": float(np.percentile(errs, 99.9)),
        "err_max_deg": float(errs.max()),
        "n_over_1_deg": int((errs > BAD_DEG).sum()),
        "per_set_max_deg": {
            k: float(v.max()) if v.size else None for k, v in row.err.items()
        },
        "n_no_truth": row.no_truth,
        "keyframes_no_truth": row.no_truth.get("keyframes", 0) + row.keyframes_in_holes,
        "n_holes": len(m["holes"]),
        "hole_days": sum(b - a for a, b in m["holes"]),
        "n_hole_samples": row.n_hole_samples,
        "hidden": row.hidden,
        "short_gap_pct": 100.0
        * row.no_truth["grid"]
        / max(1, row.no_truth["grid"] + row.err["grid"].size),
        "drift_s": row.drift_s,
        "worst": row.worst[:5],
        "seconds": row.seconds,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--missions", nargs="*", help="subset of mission dir names")
    ap.add_argument("--samples", type=int, default=3000, help="points per sample set")
    ap.add_argument("--out-dir", type=Path, default=EXPORT_DIR / "v1")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--json", type=Path, help="also write rows as JSON here")
    args = ap.parse_args()
    logging.disable(logging.INFO)

    print(
        f"{'mission':<14} {'probe':>10} {'coverage':<23} {'spans':>5} {'keyframes':>9} "
        f"{'chk':>4} {'tot_kb':>7} {'max_kb':>6} {'med°':>6} {'p95°':>6} {'p99.9°':>7} "
        f"{'max°':>7} {'>1°':>5} {'phantom':>7} {'holes':>5} {'hole_d':>7} "
        f"{'hidden':>6} {'gap%':>5} {'drift_s':>8} {'sec':>4}",
        flush=True,
    )
    rows = []
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for craft in orchestrator._load_crafts(args.out_dir):
            if args.missions and craft.mission not in args.missions:
                continue
            if craft.error:
                print(f"{craft.frame}: {craft.error}", flush=True)
                continue
            try:
                craft.coverage, needs_positions = coverage_of(args.out_dir, craft)
            except LookupError as exc:
                print(f"{craft.frame}: no coverage cache ({exc!r})", flush=True)
                continue
            if needs_positions:
                orchestrator._add_ephemerides(craft)
            for probe in orchestrator._own_probes(craft):
                row = bench_probe(ex, args.out_dir, craft, probe, args.samples)
                if row is None:
                    continue
                s = summary(row)
                if s is None:
                    print(f"{craft.frame}: no truth at any sample", flush=True)
                    continue
                rows.append(s)
                cov = f"{iso(s['start_jd'])}..{iso(s['end_jd'])}"
                print(
                    f"{s['mission']:<14} {s['probe']:>10} {cov:<23} {s['n_spans']:>5} "
                    f"{s['n_keyframes']:>9} {s['n_chunks']:>4} {s['total_kb']:>7.0f} "
                    f"{s['max_chunk_kb']:>6.0f} {s['err_med_deg']:>6.3f} "
                    f"{s['err_p95_deg']:>6.3f} {s['err_p999_deg']:>7.3f} "
                    f"{s['err_max_deg']:>7.2f} {s['n_over_1_deg']:>5} "
                    f"{s['keyframes_no_truth']:>7} {s['n_holes']:>5} "
                    f"{s['hole_days']:>7.1f} {s['hidden']:>6} "
                    f"{s['short_gap_pct']:>5.1f} {s['drift_s']:>8.4f} "
                    f"{s['seconds']:>4.0f}",
                    flush=True,
                )
    if args.json:
        args.json.write_text(json.dumps(rows, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
