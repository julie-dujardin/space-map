"""Kernels to keyframes: spin spans, adaptive samples, SLERP keyframes.

The caller furnishes SPICE. The export keyframes one 7-day shard at a time
with `extract_shard`. A non-spinner is one raw span. A spinner (Juno, HUYGENS)
has one span per stretch where a fixed-rate baseline holds, so the adaptive
sampler keyframes a slow residual. Where no baseline holds, its span is raw on
a short seed step (`segments.py`). `manifest_entry` builds the dict for the
probe's `__global__` bundle.
"""

import itertools
import logging
import math
from dataclasses import dataclass

import numpy as np
import spiceypy

from .adaptive import MIN_DT_S, adaptive_sample, point_sample
from .baseline import SpinBaseline
from .keyframes import extract_keyframes
from .sample import ck_windows, merge_windows
from .segments import SpinSegment, is_spin_plan
from .writer import ChunkFile

logger = logging.getLogger(__name__)

# Adaptive SLERP error budget. 0.1° validated as visually imperceptible at
# planet scale with near-optimal file counts.
DEFAULT_EPS_DEG = 0.1
# Apply a spin baseline only when the turn between seed samples would alias
# the sampler — below that, raw motion samples fine.
ALIAS_ANGLE_RAD = math.radians(90.0)
# Cap the span handed to one `adaptive_sample` call: its per-sample Python
# lists are ~200 B/sample, so an unbounded window (some CKs cover decades in
# one interval) at worst-case refinement density would eat GBs.
TILE_S = 4 * 86400.0
# Some CKs claim far more coverage than they hold (HUYGENS claims 45 years for
# about 4 h of data). Each sample in such a gap costs a thrown SpiceyError,
# about 30x a valid lookup. So a window longer than VALIDATE_SPAN_S is probed
# every VALIDATE_STEP_S and shrunk to the runs that resolve.
VALIDATE_SPAN_S = 10 * 86400.0
VALIDATE_STEP_S = 3600.0
# A window this short is a lone CK record, which resolves only at its instant.
# OSIRIS-REx's bus is nothing else for weeks at a time.
POINT_WINDOW_S = 1.0
# Short kernel faults and the margins of shrunk windows stay under these. More
# suggests a missing kernel or frame link.
UNRESOLVED_WARN_S = 86400.0
LOST_RECORDS_WARN = 1000

_J2000_JD = 2451545.0
_S_PER_DAY = 86400.0


@dataclass(frozen=True)
class ExtractionResult:
    """Per-probe outputs of one extraction run."""

    n_keyframes: int
    files: list[ChunkFile]
    segments: list[SpinSegment]
    coverage_start_jd: float
    coverage_end_jd: float
    holes: list[tuple[float, float]]


def _et_to_jd(et: float) -> float:
    return _J2000_JD + et / _S_PER_DAY


def log_losses(
    frame: str, unresolved_s: float, n_lost: int, claimed_s: float, kept_s: float
) -> None:
    """Log what a probe's CKs claim and SPICE does not resolve. Only a loss
    too large to be round-off or a short fault is a warning."""
    if unresolved_s:
        logger.log(
            logging.WARNING if unresolved_s > UNRESOLVED_WARN_S else logging.INFO,
            "attitude: %s — %.0f s of CK windows do not resolve",
            frame,
            unresolved_s,
        )
    if n_lost:
        logger.log(
            logging.WARNING if n_lost > LOST_RECORDS_WARN else logging.INFO,
            "attitude: %s — %d lone CK records do not resolve",
            frame,
            n_lost,
        )
    if claimed_s:
        logger.log(
            logging.WARNING if kept_s < claimed_s / 2.0 else logging.INFO,
            "attitude: %s — CK windows claim %.1f d but only %.1f d resolve; "
            "shrunk to the valid runs",
            frame,
            claimed_s / 86400.0,
            kept_s / 86400.0,
        )


def _resolves(frame_name: str, et: float) -> bool:
    try:
        spiceypy.pxform("J2000", frame_name, et)
        return True
    except spiceypy.exceptions.SpiceyError:
        return False


def _validate_windows(
    frame_name: str,
    windows: list[tuple[float, float]],
    lo: float = -math.inf,
    hi: float = math.inf,
) -> tuple[list[tuple[float, float]], float, float]:
    """Clip `windows` to `[lo, hi]` and shrink each window longer than
    `VALIDATE_SPAN_S` to its resolvable runs.

    The length test uses the whole window, so a shard of a long window is
    still probed. Only the probe grid near `[lo, hi]` is sampled, and the
    result in `[lo, hi]` is the same as for the whole window. Returns
    `(windows, claimed_s, kept_s)`, where the two totals cover only the
    windows that lost coverage.
    """
    out: list[tuple[float, float]] = []
    claimed_total = 0.0
    kept_total = 0.0
    for start, end in windows:
        if end - start <= VALIDATE_SPAN_S:
            if max(start, lo) <= min(end, hi):
                out.append((max(start, lo), min(end, hi)))
            continue
        ets = _probe_grid(start, end)
        # Two steps of margin keep the run edges outside [lo, hi] as they are.
        margin = 2.0 * VALIDATE_STEP_S
        ets = ets[(ets >= lo - margin) & (ets <= hi + margin)]
        runs: list[tuple[float, float]] = []
        run_start: float | None = None
        prev = start
        for et in ets:
            if _resolves(frame_name, float(et)):
                if run_start is None:
                    run_start = max(start, float(et) - VALIDATE_STEP_S)
                prev = float(et)
            elif run_start is not None:
                runs.append((run_start, min(end, prev + VALIDATE_STEP_S)))
                run_start = None
        if run_start is not None:
            runs.append((run_start, end))
        clipped = [(max(a, lo), min(b, hi)) for a, b in runs if max(a, lo) < min(b, hi)]
        out += clipped
        claimed = max(0.0, min(end, hi) - max(start, lo))
        kept = sum(b - a for a, b in clipped)
        if kept < claimed - VALIDATE_STEP_S:
            claimed_total += claimed
            kept_total += kept
    out.sort()
    return out, claimed_total, kept_total


def _probe_grid(start: float, end: float) -> np.ndarray:
    return np.linspace(start, end, int((end - start) / VALIDATE_STEP_S) + 2)


def scan_window_edge(
    frame_name: str, start: float, end: float, *, forward: bool
) -> float | None:
    """First (`forward`) or last edge of the resolvable runs of one long
    window, on the `_validate_windows` grid. None when nothing resolves."""
    ets = _probe_grid(start, end)
    order = range(len(ets)) if forward else range(len(ets) - 1, -1, -1)
    for i in order:
        et = float(ets[i])
        if not _resolves(frame_name, et):
            continue
        if forward:
            return max(start, et - VALIDATE_STEP_S)
        return end if i == len(ets) - 1 else min(end, et + VALIDATE_STEP_S)
    return None


@dataclass(frozen=True)
class ShardKeyframes:
    """Keyframes of one shard. `seg` is the spin span index of each one, and
    `runs` holds `(start, end)` rows: the stretches where the CKs have data."""

    ets: np.ndarray
    quats: np.ndarray
    seg: np.ndarray
    runs: np.ndarray
    unresolved_s: float
    n_lost: int
    claimed_s: float
    kept_s: float


def extract_shard(
    frame_name: str,
    ck_paths: list[str],
    instruments: list[int],
    lo: float,
    hi: float,
    spans: list[tuple[int, SpinSegment]],
    *,
    eps_deg: float = DEFAULT_EPS_DEG,
) -> ShardKeyframes:
    """Keyframe the shard `[lo, hi]` of one probe.

    The caller furnishes the base kernels and at least `ck_paths`, the CKs
    that cover the shard. `instruments` is the bus instrument, or the craft's
    other instruments when the bus has no coverage.
    `spans` holds `(span index, span clipped to the shard)` pairs; a
    non-spinner gives one raw span.
    """
    all_windows = [w for instr in instruments for w in ck_windows(ck_paths, instr)]
    windows, claimed, kept = _validate_windows(
        frame_name, merge_windows(all_windows), lo, hi
    )
    eps_rad = math.radians(eps_deg)
    ets_parts: list[np.ndarray] = [np.empty(0)]
    quat_parts: list[np.ndarray] = [np.empty((0, 4))]
    seg_parts: list[np.ndarray] = [np.empty(0, dtype=np.int16)]
    runs: list[tuple[float, float]] = []
    unresolved_s = 0.0
    n_lost = 0
    for index, seg in spans:
        ets, quats, seg_runs, unresolved, lost = _keyframe_segment(
            frame_name, seg, windows, eps_rad
        )
        runs += seg_runs
        unresolved_s += unresolved
        n_lost += lost
        ets_parts.append(ets)
        quat_parts.append(quats)
        seg_parts.append(np.full(len(ets), index, dtype=np.int16))
    return ShardKeyframes(
        ets=np.concatenate(ets_parts),
        quats=np.concatenate(quat_parts),
        seg=np.concatenate(seg_parts),
        runs=np.asarray(runs).reshape(-1, 2),
        unresolved_s=unresolved_s,
        n_lost=n_lost,
        claimed_s=claimed,
        kept_s=kept,
    )


def _keyframe_segment(
    frame_name: str,
    seg: SpinSegment,
    windows: list[tuple[float, float]],
    eps_rad: float,
) -> tuple[np.ndarray, np.ndarray, list[tuple[float, float]], float, int]:
    """Keyframe one span → `(ets, quats, runs, unresolved_s, n_lost)`.

    Tiles bound the memory of one sample stream. Each span samples its own
    endpoints, so the decoder never SLERPs across a baseline switch. `runs`
    comes from the samples, because decimation can drop the samples at the
    edges of a hole.
    """
    transform = seg.baseline.residual if seg.baseline else None
    ets_parts: list[np.ndarray] = []
    quat_parts: list[np.ndarray] = []
    runs: list[tuple[float, float]] = []
    last_et = -math.inf
    unresolved_s = 0.0
    n_lost = 0

    def keep_keyframes(ets: np.ndarray, stream: np.ndarray) -> None:
        nonlocal last_et
        keep = [i for i in extract_keyframes(stream, ets, eps_rad) if ets[i] > last_et]
        if keep:
            ets_parts.append(ets[keep])
            quat_parts.append(stream[keep])
            last_et = float(ets[keep[-1]])

    for is_point, run in itertools.groupby(windows, key=_is_point):
        if is_point:
            instants = [
                a for a, _ in run if max(seg.start_et, last_et) <= a <= seg.end_et
            ]
            ets, stream, lost = point_sample(frame_name, instants, transform)
            n_lost += lost
            runs += [(et, et) for et in ets.tolist()]
            keep_keyframes(ets, stream)
            continue
        for win_start, win_end in run:
            start = max(win_start, seg.start_et, last_et)
            end = min(win_end, seg.end_et)
            while start < end:
                tile_end = min(end, start + TILE_S)
                # A raw fast spin turns degrees per second and its CK records
                # kink the rate, so its refinement floor scales with its seed
                # step.
                ets, stream, unresolved = adaptive_sample(
                    frame_name,
                    start,
                    tile_end,
                    eps_rad,
                    seed_dt=seg.seed_dt,
                    min_dt=min(MIN_DT_S, seg.seed_dt / 4),
                    transform=transform,
                )
                unresolved_s += sum(b - a for a, b in unresolved)
                runs += _data_runs(ets, unresolved)
                keep_keyframes(ets, stream)
                start = tile_end
    if not quat_parts:
        return np.empty(0), np.empty((0, 4)), runs, unresolved_s, n_lost
    return (
        np.concatenate(ets_parts),
        np.concatenate(quat_parts),
        runs,
        unresolved_s,
        n_lost,
    )


def _data_runs(
    ets: np.ndarray, unresolved: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    """The stretches of the ascending samples `ets` that no `unresolved`
    stretch splits."""
    if not ets.size:
        return []
    cuts = np.unique(np.searchsorted(ets, [a for a, _ in unresolved]))
    cuts = cuts[(cuts > 0) & (cuts < ets.size)]
    firsts = np.concatenate([[0], cuts])
    lasts = np.concatenate([cuts - 1, [ets.size - 1]])
    return list(zip(ets[firsts].tolist(), ets[lasts].tolist(), strict=True))


def _is_point(window: tuple[float, float]) -> bool:
    return window[1] - window[0] <= POINT_WINDOW_S


def _baseline_json(seg: SpinSegment) -> dict:
    """Serialise one span's baseline for the manifest `baselines` timeline.

    A raw span is a spin at rate 0 from the identity, so the deployed frontend
    composes it to identity and reads its keyframes as they are.
    """
    b = seg.baseline or SpinBaseline(
        np.array([0.0, 0.0, 1.0]), 0.0, np.array([1.0, 0.0, 0.0, 0.0]), seg.start_et
    )
    return {
        "kind": "spin",
        "axis": [float(a) for a in b.axis],
        "rate_rad_s": float(b.rate_rad_s),
        "anchor": [float(a) for a in b.anchor],
        "anchor_jd": _et_to_jd(b.t0),
        "start_jd": _et_to_jd(seg.start_et),
        "end_jd": _et_to_jd(seg.end_et),
    }


def manifest_entry(result: ExtractionResult, *, frame_name: str) -> dict:
    """Build the `attitude` dict the writer injects into the probe's
    `__global__` object entry.

    Schema:
        {
          "source": "spice_ck",
          "frame": str,
          "start_jd": float,
          "end_jd": float,
          "n_keyframes": int,
          "baselines": [
            {"kind": "spin", "axis": [x,y,z], "rate_rad_s": float,
             "anchor": [w,x,y,z], "anchor_jd": float,
             "start_jd": float, "end_jd": float}, ...
          ] | null,
          "files": [{"name", "start_jd", "end_jd", "n_keyframes",
                     "baseline_index"?}, ...],
          "holes": [[start_jd, end_jd], ...]
        }

    `baselines` is null for a non-spinner. For a spinner, each file's
    `baseline_index` selects the active span to recompose against. A raw span
    of a spinner has `rate_rad_s` 0, `anchor` [1, 0, 0, 0] and `axis`
    [0, 0, 1], so it composes to identity. `holes` lists the gaps of at least
    `HOLE_MIN_S` in the CK data, in time order, which a decoder does not
    interpolate across.
    """
    spinning = is_spin_plan(result.segments)
    baselines = [_baseline_json(seg) for seg in result.segments] if spinning else None
    files = []
    for f in result.files:
        entry = {
            "name": f.name,
            "start_jd": f.start_jd,
            "end_jd": f.end_jd,
            "n_keyframes": f.n_keyframes,
        }
        if spinning:
            entry["baseline_index"] = f.baseline_index
        files.append(entry)
    return {
        "source": "spice_ck",
        "frame": frame_name,
        "start_jd": result.coverage_start_jd,
        "end_jd": result.coverage_end_jd,
        "n_keyframes": result.n_keyframes,
        "baselines": baselines,
        "files": files,
        "holes": [[_et_to_jd(a), _et_to_jd(b)] for a, b in result.holes],
    }
