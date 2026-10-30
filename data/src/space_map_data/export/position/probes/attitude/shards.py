"""Shard planning for the probe attitude cache.

A shard is a fixed 7-day slice of time. The grid starts at ET 0, so shard
edges do not move between runs. A shard furnishes only the CKs that cover
it, and its keyframes are cached under a signature of all its inputs. A run
extracts again only the shards whose signature changed.

Everything here is plain data and needs no SPICE.
"""

import hashlib
import json
import math
from collections.abc import Callable, Iterable
from dataclasses import replace

import numpy as np

from .extractor import VALIDATE_SPAN_S
from .sample import craft_instruments
from .segments import SpinSegment

SHARD_S = 7 * 86400.0

Window = tuple[float, float]
# CK name -> {instrument id -> SEGMENT-level windows}.
Coverage = dict[str, dict[int, list[Window]]]
# (start, end, forward) -> edge of the resolvable runs, or None.
EdgeScan = Callable[[float, float, bool], float | None]


def shard_bounds(k: int) -> Window:
    return k * SHARD_S, (k + 1) * SHARD_S


def shards_overlapping(start: float, end: float) -> range:
    """Shards k with `k * SHARD_S < end` and `(k + 1) * SHARD_S > start`."""
    return range(math.floor(start / SHARD_S), math.ceil(end / SHARD_S))


def digest(obj: object) -> str:
    """Short stable hash of a JSON-able object."""
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.blake2b(raw, digest_size=10).hexdigest()


def probe_instruments(coverage: Coverage, bus: int) -> list[int]:
    """The bus instrument, or the craft's other instruments when the bus has
    no coverage. Some bus frames switch to a sub-instrument (Hera uses
    -91002)."""
    if any(cover.get(bus) for cover in coverage.values()):
        return [bus]
    return craft_instruments(
        {i for cover in coverage.values() for i in cover} - {bus}, bus
    )


def probe_windows(
    coverage: Coverage, ck_names: list[str], instruments: list[int]
) -> list[Window]:
    """SEGMENT-level windows of `instruments`, one per CK segment, sorted."""
    return sorted(
        w
        for name in ck_names
        for instr in instruments
        for w in coverage[name].get(instr, [])
    )


def span_edges(windows: list[Window], scan: EdgeScan) -> Window | None:
    """First and last resolvable epochs over `windows`.

    A window up to `VALIDATE_SPAN_S` counts as whole. A longer one is a claim
    to check, so `scan` finds its resolvable edge. Returns None when nothing
    resolves.
    """
    t0 = math.inf
    for start, end in sorted(windows):
        if start >= t0:
            break
        edge = start if end - start <= VALIDATE_SPAN_S else scan(start, end, True)
        if edge is not None:
            t0 = min(t0, edge)
    t1 = -math.inf
    for start, end in sorted(windows, key=lambda w: w[1], reverse=True):
        if end <= t1:
            break
        edge = end if end - start <= VALIDATE_SPAN_S else scan(start, end, False)
        if edge is not None:
            t1 = max(t1, edge)
    if t0 > t1:
        return None
    return t0, t1


def plan_shards(
    coverage: Coverage, ck_names: list[str], instruments: list[int], span: Window
) -> dict[int, list[str]]:
    """The probe's shards inside `span`, each with the CKs that cover it.

    A shard exists where one of `instruments` has coverage. Its CK list holds
    every CK with coverage there for any instrument, in index order: a frame
    can chain through another instrument's CK, and load order sets SPICE
    priority.
    """
    t0, t1 = span
    probe_ks: set[int] = set()
    cks_by_k: dict[int, list[str]] = {}
    for name in ck_names:
        ks_any: set[int] = set()
        for instr, windows in coverage[name].items():
            for start, end in windows:
                ks = shards_overlapping(max(start, t0), min(end, t1))
                ks_any.update(ks)
                if instr in instruments:
                    probe_ks.update(ks)
        for k in ks_any:
            cks_by_k.setdefault(k, []).append(name)
    return {k: cks_by_k[k] for k in sorted(probe_ks)}


def covering_cks(
    coverage: Coverage, ck_names: list[str], start: float, end: float
) -> list[str]:
    """CKs with coverage for any instrument in `[start, end]`, in index order."""
    return [
        name
        for name in ck_names
        if any(
            a <= end and b >= start
            for windows in coverage[name].values()
            for a, b in windows
        )
    ]


def shard_spans(
    k: int, segments: list[SpinSegment] | None
) -> list[tuple[int, SpinSegment]]:
    """`(span index, span clipped to shard k)` pairs. A non-spinner
    (`segments` None) gets one raw span over the whole shard."""
    lo, hi = shard_bounds(k)
    if segments is None:
        return [(0, SpinSegment(lo, hi, None))]
    return [
        (i, replace(seg, start_et=max(seg.start_et, lo), end_et=min(seg.end_et, hi)))
        for i, seg in enumerate(segments)
        if seg.start_et < hi and seg.end_et > lo
    ]


def segment_json(seg: SpinSegment) -> dict:
    b = seg.baseline
    return {
        "start": seg.start_et,
        "end": seg.end_et,
        "seed_dt": seg.seed_dt,
        "baseline": None
        if b is None
        else {
            "axis": [float(a) for a in b.axis],
            "rate": float(b.rate_rad_s),
            "anchor": [float(a) for a in b.anchor],
            "t0": float(b.t0),
        },
    }


def clock_signature(rows: np.ndarray, k: int) -> str:
    """Digest of the SCLK rows that reach shard k.

    `rows` holds `(ticks, parallel time, rate)` rows. A new SCLK adds rows and
    changes at most the rate of its last old row, so the shards before that
    row keep their signature.
    """
    _, hi = shard_bounds(k)
    return hashlib.blake2b(rows[rows[:, 1] <= hi].tobytes(), digest_size=10).hexdigest()


def shard_signature(
    probe_sig: dict,
    cks: list[list],
    spans: list[tuple[int, SpinSegment]] | None,
    clock: str,
) -> str:
    """Digest of all inputs of one shard.

    `probe_sig` holds the inputs shared by all shards of a probe. `cks` is
    `[name, stamp]` for the shard's CKs in index order. `spans` is None for a
    non-spinner, whose shards do not depend on the spin plan. `clock` is the
    shard's `clock_signature`.
    """
    return digest(
        {
            "probe": probe_sig,
            "cks": cks,
            "clock": clock,
            "spans": None
            if spans is None
            else [[i, segment_json(seg)] for i, seg in spans],
        }
    )


def join_shards(
    parts: Iterable[tuple[np.ndarray, np.ndarray, np.ndarray]], n_spans: int
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Join shard keyframes, in shard order, into one stream per spin span.

    Adjacent shards share their edge sample, so a keyframe at or before the
    last kept one is dropped. Each stream is strictly rising in time.
    """
    ets_out: list[list[np.ndarray]] = [[] for _ in range(n_spans)]
    quats_out: list[list[np.ndarray]] = [[] for _ in range(n_spans)]
    last = [-math.inf] * n_spans
    for ets, quats, seg in parts:
        for i in np.unique(seg):
            mask = seg == i
            e, q = ets[mask], quats[mask]
            prev = np.maximum.accumulate(np.concatenate([[last[i]], e]))[:-1]
            keep = e > prev
            if keep.any():
                ets_out[i].append(e[keep])
                quats_out[i].append(q[keep])
                last[i] = float(e[keep][-1])
    return [
        (
            np.concatenate(ets_out[i]) if ets_out[i] else np.empty(0),
            np.concatenate(quats_out[i]) if quats_out[i] else np.empty((0, 4)),
        )
        for i in range(n_spans)
    ]


def split_runs(
    ks: list[int], cost: Callable[[int], float], target: float
) -> list[list[int]]:
    """Cut sorted shard indices into runs of consecutive shards, each with a
    total `cost` near `target` at most (a single shard can exceed it)."""
    runs: list[list[int]] = []
    current: list[int] = []
    total = 0.0
    for k in ks:
        c = cost(k)
        if current and (k != current[-1] + 1 or total + c > target):
            runs.append(current)
            current, total = [], 0.0
        current.append(k)
        total += c
    if current:
        runs.append(current)
    return runs
