"""Sample J2000→body-frame quaternions from a furnished SPICE CK.

Kept thin: we own the time-grid generation and continuous-sign canonicalisation
(adjacent samples differ by < 90° as quaternions), so downstream keyframe
extraction and baseline fits can treat the stream as smooth.
"""

import logging

import numpy as np
import spiceypy

logger = logging.getLogger(__name__)


def ck_windows(ck_paths: list[str], instr_id: int) -> list[tuple[float, float]]:
    """Per-file (start_et, end_et) coverage for `instr_id`, ascending by start.

    One window per CK (its outer interval envelope), in TDB seconds. Files
    with no coverage for `instr_id` are skipped — a mission set mixes bus CKs
    with instrument-articulation ones. Windows may overlap; the caller trims.
    """
    windows: list[tuple[float, float]] = []
    for path in ck_paths:
        cover = spiceypy.support_types.SPICEDOUBLE_CELL(100_000)
        try:
            spiceypy.ckcov(path, instr_id, False, "INTERVAL", 0.0, "TDB", cover)
        except spiceypy.exceptions.SpiceyError:
            logger.warning("attitude: ckcov failed for %s, skipping", path)
            continue
        if len(cover) >= 2:
            windows.append((float(cover[0]), float(cover[len(cover) - 1])))
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
