"""Sample J2000→body-frame quaternions from a furnished SPICE CK.

Kept thin: we own the time-grid generation and continuous-sign canonicalisation
(adjacent samples differ by < 90° as quaternions), so downstream keyframe
extraction and baseline fits can treat the stream as smooth.
"""

import logging

import numpy as np
import spiceypy

logger = logging.getLogger(__name__)

# Overflow raises SPICE(CELLTOOSMALL) and loses the file's coverage; busiest
# reconstructed CKs (Cassini/MRO) run to a few thousand spans.
_COVER_CELL_SIZE = 1_000_000


def ck_windows(ck_paths: list[str], instr_id: int) -> list[tuple[float, float]]:
    """Gap-free (start_et, end_et) coverage spans for `instr_id`, TDB, sorted.

    One entry per real interval, not the file's outer envelope: an envelope's
    holes cost a thrown `SpiceyError` per in-gap sample downstream — millions
    for a sparse CK. Files with no coverage for `instr_id` are skipped (a
    mission mixes bus and instrument-articulation CKs); spans may overlap.
    """
    windows: list[tuple[float, float]] = []
    for path in ck_paths:
        cover = spiceypy.support_types.SPICEDOUBLE_CELL(_COVER_CELL_SIZE)
        try:
            spiceypy.ckcov(path, instr_id, False, "INTERVAL", 0.0, "TDB", cover)
        except spiceypy.exceptions.SpiceyError:
            logger.warning("attitude: ckcov failed for %s, skipping", path)
            continue
        for i in range(spiceypy.wncard(cover)):
            start, end = spiceypy.wnfetd(cover, i)
            windows.append((float(start), float(end)))
    windows.sort()
    return windows


def sample_truth(frame: str, ets: np.ndarray) -> np.ndarray:
    """Sample `pxform("J2000", frame, et)` → quaternion for each `et`.

    Sign-canonicalises against the previous sample so the stream is
    continuous (adjacent quats differ by < 90°). SPICE's `m2q` flips sign
    at trace zero crossings, which adaptive keyframes would otherwise
    have to chase with extra emits.
    """
    quats = np.empty((ets.size, 4), dtype=np.float64)
    last = np.array([1.0, 0.0, 0.0, 0.0])
    failed = 0
    for i, et in enumerate(ets):
        try:
            q = spiceypy.m2q(spiceypy.pxform("J2000", frame, float(et)))
        except spiceypy.exceptions.SpiceyError:
            failed += 1
            # Repeat the last good sample so the time series stays defined;
            # adaptive SLERP will collapse the flat run to a single keyframe.
            q = last
        if np.dot(q, last) < 0:
            q = -q
        quats[i] = q
        last = q
    if failed:
        logger.warning(
            "pxform failed for %d/%d samples on frame %s — repeated last good sample",
            failed,
            ets.size,
            frame,
        )
    return quats
