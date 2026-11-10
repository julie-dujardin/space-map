"""SPK coverage helpers shared by the bodies, probes and export passes.

Kept free of the download providers' package imports, so any of them can use
it without an import cycle.
"""

from pathlib import Path

import spiceypy


def merge_intervals(
    intervals: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Merge overlapping/touching intervals; sorted by start."""
    if not intervals:
        return []
    sorted_iv = sorted(intervals)
    merged: list[tuple[float, float]] = [sorted_iv[0]]
    for start, stop in sorted_iv[1:]:
        last_start, last_stop = merged[-1]
        if start <= last_stop:
            merged[-1] = (last_start, max(last_stop, stop))
        else:
            merged.append((start, stop))
    return merged


def coverage_windows(
    paths: list[Path], naif_id: int, cell
) -> list[tuple[float, float]]:
    """Merged `(start_et, end_et)` intervals covering `naif_id` across `paths`.

    Takes a caller-owned cell rather than calling `spk_coverage`, which
    allocates a 200k-double cell per call — Bennu alone matches 335 OSIRIS-REx
    kernels, and SPICE cells are only reclaimed lazily. Paths SPICE can't read
    as an SPK (PCKs, LSKs) contribute nothing.
    """
    raw: list[tuple[float, float]] = []
    for path in paths:
        spiceypy.scard(0, cell)
        try:
            spiceypy.spkcov(str(path), naif_id, cell)
        except spiceypy.exceptions.SpiceyError:
            continue
        for i in range(spiceypy.wncard(cell)):
            lo, hi = spiceypy.wnfetd(cell, i)
            if hi > lo:
                raw.append((lo, hi))
    return merge_intervals(raw)


def clip_windows(
    windows: list[tuple[float, float]], lo: float, hi: float
) -> list[tuple[float, float]]:
    """`windows` cut to `[lo, hi]`, dropping those left with no length."""
    return [
        (max(w_lo, lo), min(w_hi, hi))
        for w_lo, w_hi in windows
        if w_hi > lo and w_lo < hi
    ]
