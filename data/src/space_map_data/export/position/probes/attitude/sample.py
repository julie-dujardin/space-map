"""Sample J2000→body-frame quaternions from a furnished SPICE CK.

Kept thin: we own the time-grid generation and continuous-sign canonicalisation
(adjacent samples differ by < 90° as quaternions), so downstream keyframe
extraction and baseline fits can treat the stream as smooth.
"""

import logging

import numpy as np
import spiceypy

logger = logging.getLogger(__name__)


def ck_coverage(ck_path: str, instr_id: int) -> tuple[float, float]:
    """Return the CK's (start_et, end_et) for `instr_id` as TDB seconds.

    Walks every interval in the kernel; returns the outer envelope. Gaps
    in CK coverage are silently absorbed — `sample_truth` will repeat the
    last good quaternion across gaps, which adaptive keyframes then
    collapse into a single segment.
    """
    cover = spiceypy.support_types.SPICEDOUBLE_CELL(100_000)
    spiceypy.ckcov(ck_path, instr_id, False, "INTERVAL", 0.0, "TDB", cover)
    if len(cover) < 2:
        raise ValueError(f"CK {ck_path!r} has no coverage for instrument {instr_id}")
    return float(cover[0]), float(cover[len(cover) - 1])


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
