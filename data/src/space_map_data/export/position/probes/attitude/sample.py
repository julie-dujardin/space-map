"""Sample J2000→body-frame quaternions from a furnished SPICE CK.

Kept thin: we own the time-grid generation and continuous-sign canonicalisation
(adjacent samples differ by < 90° as quaternions), so downstream keyframe
extraction and baseline fits can treat the stream as smooth.
"""

import functools
import logging

import numpy as np
import spiceypy

logger = logging.getLogger(__name__)

# Overflow raises SPICE(CELLTOOSMALL) and loses the file's coverage; busiest
# reconstructed CKs (Cassini/MRO) run to a few thousand spans.
_COVER_CELL_SIZE = 1_000_000
_IDS_CELL_SIZE = 10_000


# One cell of each kind per process. spiceypy cells are about 8 MB and Python
# frees them late, so a new cell per call holds GBs over thousands of CKs.
@functools.cache
def _cover_cell():
    return spiceypy.support_types.SPICEDOUBLE_CELL(_COVER_CELL_SIZE)


@functools.cache
def _ids_cell():
    return spiceypy.support_types.SPICEINT_CELL(_IDS_CELL_SIZE)


def craft_instruments(carried: set[int], bus: int) -> list[int]:
    """The IDs in `carried` of the craft with bus instrument `bus`. A CK
    instrument ID is the NAIF ID of its craft times 1000 plus an offset, so a
    capsule or a lander finds none in its mission's CKs."""
    return sorted(i for i in carried if int(i / 1000) * 1000 == bus)


def ck_windows(ck_paths: list[str], instr_id: int) -> list[tuple[float, float]]:
    """Coverage intervals of `instr_id` in `ck_paths`, TDB, sorted and merged
    where they overlap.

    Each entry is one real interval, not the outer envelope of a file. Each
    sample in a gap of an envelope costs a thrown `SpiceyError`, and a sparse
    CK has millions of such samples.
    """
    windows: list[tuple[float, float]] = []
    cover = _cover_cell()
    for path in ck_paths:
        spiceypy.scard(0, cover)
        try:
            spiceypy.ckcov(path, instr_id, False, "INTERVAL", 0.0, "TDB", cover)
        except spiceypy.exceptions.SpiceyError:
            logger.warning("attitude: ckcov failed for %s, skipping", path)
            continue
        for i in range(spiceypy.wncard(cover)):
            start, end = spiceypy.wnfetd(cover, i)
            windows.append((float(start), float(end)))
    windows.sort()
    merged: list[tuple[float, float]] = []
    for start, end in windows:
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
            continue
        merged.append((start, end))
    return merged


def ck_instrument_ids(ck_paths: list[str]) -> set[int]:
    """Union of CK instrument IDs present across `ck_paths`."""
    ids: set[int] = set()
    cell = _ids_cell()
    for path in ck_paths:
        spiceypy.scard(0, cell)
        try:
            spiceypy.ckobj(path, cell)
        except spiceypy.exceptions.SpiceyError:
            logger.warning("attitude: ckobj failed for %s, skipping", path)
            continue
        ids |= {int(cell[i]) for i in range(spiceypy.card(cell))}
    return ids


def ck_segment_coverage(path: str) -> dict[int, list[tuple[float, float]]]:
    """SEGMENT-level TDB coverage of one CK, per instrument it carries.

    Needs the LSK, the FK and the mission SCLK furnished. An instrument with
    no SCLK loaded is left out, because SPICE cannot read its data either.
    Raises `SpiceyError` on an unreadable file.
    """
    ids = _ids_cell()
    cover = _cover_cell()
    spiceypy.scard(0, ids)
    spiceypy.ckobj(path, ids)
    out: dict[int, list[tuple[float, float]]] = {}
    for i in range(spiceypy.card(ids)):
        instr = int(ids[i])
        spiceypy.scard(0, cover)
        try:
            spiceypy.ckcov(path, instr, False, "SEGMENT", 0.0, "TDB", cover)
        except spiceypy.exceptions.SpiceyError as exc:
            if exc.short != "SPICE(KERNELVARNOTFOUND)":
                raise
            logger.warning("attitude: no SCLK for instrument %d in %s", instr, path)
            continue
        out[instr] = [
            (float(a), float(b))
            for a, b in (
                spiceypy.wnfetd(cover, j) for j in range(spiceypy.wncard(cover))
            )
        ]
    return out


def ck_needs_ephemeris(path: str, cover: dict[int, list[tuple[float, float]]]) -> bool:
    """True when a segment of the CK is relative to a frame that resolves only
    with positions. HUYGENS gives its descent relative to a frame that points
    at Titan, so it resolves only with the mission's SPKs.

    `cover` is the CK's `ck_segment_coverage`. Each reference frame is tried
    from J2000 at the start of its instrument's coverage, with no SPK loaded.
    A frame that resolves, or fails for any other reason, needs no SPK.
    """
    handle = spiceypy.dafopr(path)
    pairs: set[tuple[int, int]] = set()
    try:
        spiceypy.dafbfs(handle)
        while spiceypy.daffna():
            _, ints = spiceypy.dafus(spiceypy.dafgs(), 2, 6)
            pairs.add((int(ints[0]), int(ints[1])))
    finally:
        spiceypy.dafcls(handle)
    for instr, ref in pairs:
        name = spiceypy.frmnam(ref)
        if not name or not cover.get(instr):
            continue
        try:
            spiceypy.pxform("J2000", name, cover[instr][0][0])
        except spiceypy.exceptions.SpiceyError as exc:
            # SPKSFS is the SPK search; it fails this way when no SPK is loaded.
            if exc.short == "SPICE(NOLOADEDFILES)" and exc.traceback.endswith("SPKSFS"):
                return True
    return False


def sample_truth(frame: str, ets: np.ndarray) -> np.ndarray:
    """Sample `pxform("J2000", frame, et)` → quaternion for each `et`.
    Sign-canonicalised against the previous sample (adjacent quats differ
    by < 90°) — SPICE's `m2q` flips sign at trace zero crossings, which
    adaptive keyframes would otherwise chase with extra emits.
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
