"""Tasks the attitude step runs in worker processes.

SPICE state is per process. Each task furnishes what it needs, does its work
and calls `kclear`. Arguments and results are plain data, so they pickle.
"""

import os
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import spiceypy

from .cache import save_shard
from .extractor import extract_shard, scan_window_edge
from .sample import ck_needs_ephemeris, ck_segment_coverage
from .segments import (
    SpinSegment,
    segments_from_timeline,
    spin_omegas,
)
from .shards import Window, shard_bounds, span_edges

# NAS reads are fastest in large sequential blocks.
_READ_BLOCK = 8 << 20
_MAX_SCLK_CLOCKS = 16


def _furnish(paths: list[str]) -> None:
    spiceypy.kclear()
    for path in paths:
        spiceypy.furnsh(path)


def coverage_task(base: list[str], ck_paths: list[str]) -> dict[str, dict | str]:
    """`{"cover", "ephemeris"}` of each CK: its SEGMENT-level coverage and
    whether it needs positions, or the error text for an unreadable one.
    `base` holds the base kernels, so the FK maps each CK to its SCLK and
    defines the frames its segments are relative to."""
    _furnish(base)
    out: dict[str, dict | str] = {}
    try:
        for path in ck_paths:
            try:
                cover = ck_segment_coverage(path)
                out[path] = {
                    "cover": cover,
                    "ephemeris": ck_needs_ephemeris(path, cover),
                }
            except spiceypy.exceptions.SpiceyError as exc:
                out[path] = str(exc)
    finally:
        spiceypy.kclear()
    return out


def sclk_task(path: str) -> np.ndarray:
    """The `(ticks, parallel time, rate)` rows of an SCLK kernel. SPICE reads
    them because some kernels give the times as dates."""
    _furnish([path])
    try:
        names = sorted(spiceypy.gnpool("SCLK01_COEFFICIENTS_*", 0, _MAX_SCLK_CLOCKS))
        rows = [spiceypy.gdpool(n, 0, spiceypy.dtpool(n)[0]) for n in names]
    finally:
        spiceypy.kclear()
    return np.concatenate(rows).reshape(-1, 3)


def edge_task(
    base: list[str], ck_paths: list[str], frame: str, windows: list[Window]
) -> Window | None:
    """`span_edges` with SPICE scans of the long windows."""
    _furnish(base + ck_paths)
    try:
        return span_edges(
            windows,
            lambda a, b, forward: scan_window_edge(frame, a, b, forward=forward),
        )
    finally:
        spiceypy.kclear()


def timeline_task(
    base: list[str], ck_paths: list[str], frame: str, ets: np.ndarray
) -> list[np.ndarray | None]:
    """Spin timeline omegas at `ets`. `ck_paths` must cover `ets`."""
    _furnish(base + ck_paths)
    try:
        return spin_omegas(frame, ets)
    finally:
        spiceypy.kclear()


def fit_task(
    base: list[str],
    ck_paths: list[str],
    frame: str,
    span: Window,
    ets: np.ndarray,
    omegas: list[np.ndarray | None],
    alias_angle: float,
    seed_dt: float,
) -> list[SpinSegment]:
    """Spin phases and baselines of a spinner, from its timeline."""
    _furnish(base + ck_paths)
    try:
        return segments_from_timeline(
            frame,
            span[0],
            span[1],
            ets,
            omegas,
            alias_angle=alias_angle,
            seed_dt=seed_dt,
        )
    finally:
        spiceypy.kclear()


@dataclass(frozen=True)
class ShardJob:
    """One probe's shard to extract."""

    probe_id: int
    k: int
    frame: str
    instruments: list[int]
    ck_paths: list[str]
    spans: list[tuple[int, SpinSegment]]
    out_path: str


@dataclass(frozen=True)
class ShardTask:
    """A run of consecutive shards of one mission.

    `ck_paths` are all CKs of the task in index order. `shards` holds
    `(k, CK paths of shard k)` in order; `jobs` holds the probes to extract
    at each k.
    """

    base: list[str]
    ck_paths: list[str]
    shards: list[tuple[int, list[str]]]
    jobs: dict[int, list[ShardJob]]


@dataclass(frozen=True)
class ShardResult:
    probe_id: int
    k: int
    n_keyframes: int
    n_gaps: int
    claimed_s: float
    kept_s: float
    error: str | None


@dataclass(frozen=True)
class ShardTaskResult:
    results: list[ShardResult]
    bytes_read: int
    read_s: float


def shard_task(task: ShardTask) -> ShardTaskResult:
    """Extract and save each job of the task, one shard after another.

    The CKs of the next shard are read in the background while the current
    one extracts, so SPICE finds them in the page cache. Pages of a CK are
    dropped when no later shard of the task needs it.
    """
    _furnish(task.base + task.ck_paths)
    last_use = {p: i for i, (_, paths) in enumerate(task.shards) for p in paths}
    reader = _ReadAhead()
    results: list[ShardResult] = []
    try:
        reader.start(task.shards[0][1])
        for i, (k, paths) in enumerate(task.shards):
            reader.wait(paths)
            if i + 1 < len(task.shards):
                reader.start(task.shards[i + 1][1])
            lo, hi = shard_bounds(k)
            for job in task.jobs.get(k, []):
                results.append(_extract_job(job, lo, hi))
            reader.drop([p for p in paths if last_use[p] == i])
    finally:
        reader.close()
        spiceypy.kclear()
    return ShardTaskResult(results, reader.bytes_read, reader.read_s)


def _extract_job(job: ShardJob, lo: float, hi: float) -> ShardResult:
    try:
        kf = extract_shard(job.frame, job.ck_paths, job.instruments, lo, hi, job.spans)
        save_shard(Path(job.out_path), kf.ets, kf.quats, kf.seg)
    except Exception as exc:
        return ShardResult(job.probe_id, job.k, 0, 0, 0.0, 0.0, repr(exc))
    return ShardResult(
        job.probe_id, job.k, len(kf.ets), kf.n_gaps, kf.claimed_s, kf.kept_s, None
    )


class _ReadAhead:
    """Reads whole files on one background thread, in large blocks."""

    def __init__(self) -> None:
        self._pool = ThreadPoolExecutor(max_workers=1)
        self._reads: dict[str, Future[int]] = {}
        self.bytes_read = 0
        self.read_s = 0.0

    def start(self, paths: list[str]) -> None:
        for path in paths:
            if path not in self._reads:
                self._reads[path] = self._pool.submit(self._read, path)

    def wait(self, paths: list[str]) -> None:
        self.start(paths)
        for path in paths:
            self._reads[path].result()

    def drop(self, paths: list[str]) -> None:
        for path in paths:
            future = self._reads.pop(path, None)
            if future is not None and future.exception() is None:
                _drop_pages(path)

    def close(self) -> None:
        self.drop(list(self._reads))
        self._pool.shutdown()

    def _read(self, path: str) -> int:
        t = time.monotonic()
        buf = bytearray(_READ_BLOCK)
        n = 0
        with open(path, "rb", buffering=0) as f:
            while chunk := f.readinto(buf):
                n += chunk
        self.bytes_read += n
        self.read_s += time.monotonic() - t
        return n


def _drop_pages(path: str) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
    finally:
        os.close(fd)
