"""Adaptive geodesic sampling of a CK attitude window.

A fixed cadence either aliases fast motion or wastes samples on geodesic
cruise. Instead: seed a coarse grid, then recursively subdivide any segment
whose interior truth deviates from the SLERP of its endpoints past the error
budget, probing several interior points so a brief maneuver can't slip
through on a lucky midpoint. A segment with an end or a probe that does not
resolve has an edge of the CK's data in it, so it subdivides until the edge is
found. Output is raw J2000->body, or the spin-baseline residual when
`transform` is given; `extract_keyframes` decimates it later.
"""

import itertools
import math
from collections.abc import Callable

import numpy as np
import spiceypy

from .quaternion import angle_between, slerp

# Coarse seed cadence (s): fine enough to keep an un-baselined spinner under
# half a turn per segment, coarse enough to keep cruise cheap. Fast spinners
# are baseline-subtracted first, so their residual is slow and this is safe.
SEED_DT_S = 300.0
# Refinement floor for motion — a segment this short is held to `JUMP_RAD`.
MIN_DT_S = 1.0
# A CK can jump: a seam between files, a bad record, an edge of its data.
# Refinement closes on those down to `FINE_DT_S`, so a jump stays as narrow as
# it is in the kernel, and smooth motion takes no more keyframes. A probe can
# see half of a jump, so this catches jumps from 1 degree.
JUMP_RAD = math.radians(0.5)
FINE_DT_S = 1e-3
# Interior probe fractions per segment. Three points bound the largest
# unprobed gap at a quarter of the segment, catching brief slews.
PROBE_FRACS = (0.25, 0.5, 0.75)
Transform = Callable[[float, np.ndarray], np.ndarray]


def adaptive_sample(
    frame: str,
    t0: float,
    t1: float,
    eps_rad: float,
    *,
    seed_dt: float = SEED_DT_S,
    min_dt: float = MIN_DT_S,
    transform: Transform | None = None,
) -> tuple[np.ndarray, np.ndarray, list[tuple[float, float]]]:
    """Sample `[t0, t1]` adaptively → ascending `(ets, quats, unresolved)`.

    `transform(et, q_raw)` maps raw J2000->body truth to the stream we keyframe
    (the baseline residual); identity when None. Quats are sign-canonicalised
    continuously so downstream SLERP and smallest-three packing stay smooth.
    A sample that does not resolve yields no keyframe, since any value for it
    would be invented, and the samples close in on the edges of the data. A
    stretch of data that falls between all the probes of a seed step stays
    unseen. `unresolved` holds the stretches found to have no data, in order.
    """
    unresolved: list[tuple[float, float]] = []
    out_t: list[float] = []
    out_q: list[np.ndarray] = []

    def truth(et: float) -> np.ndarray | None:
        return _stream_at(frame, et, transform)

    def emit(et: float, q: np.ndarray | None) -> None:
        if q is not None:
            out_t.append(et)
            out_q.append(q)

    def refine(
        ta: float, qa: np.ndarray | None, tb: float, qb: np.ndarray | None, depth: int
    ) -> None:
        if tb - ta <= FINE_DT_S or depth > 40:
            return
        samples = [(et, truth(et)) for et in (ta + f * (tb - ta) for f in PROBE_FRACS)]
        resolved = [q for _, q in samples if q is not None]
        if qa is None and qb is None and not resolved:
            unresolved.append((ta, tb))
            return
        if qa is None or qb is None or len(resolved) < len(samples):
            cuts = samples
        else:
            errs = [
                angle_between(slerp(qa, qb, f), q)
                for f, q in zip(PROBE_FRACS, resolved, strict=True)
            ]
            worst = int(np.argmax(errs))
            if errs[worst] <= (eps_rad if tb - ta > min_dt else JUMP_RAD):
                return
            cuts = [samples[worst]]
        left = (ta, qa)
        for cut in cuts:
            refine(*left, *cut, depth + 1)
            emit(*cut)
            left = cut
        refine(*left, tb, qb, depth + 1)

    n_seed = max(2, round((t1 - t0) / seed_dt) + 1)
    seeds = [(et, truth(et)) for et in np.linspace(t0, t1, n_seed).tolist()]
    emit(*seeds[0])
    for (ta, qa), (tb, qb) in itertools.pairwise(seeds):
        refine(ta, qa, tb, qb, 0)
        emit(tb, qb)

    quats = np.asarray(out_q).reshape(-1, 4)
    _canonicalise(quats)
    return np.asarray(out_t), quats, unresolved


def point_sample(
    frame: str, ets: list[float], transform: Transform | None = None
) -> tuple[np.ndarray, np.ndarray, int]:
    """Sample the instants of point windows → `(ets, quats, n_lost)`.

    A point window resolves only at its one instant, so an instant that rounds
    off its record is left out: nothing nearby can stand in for it.
    """
    kept: list[float] = []
    stream: list[np.ndarray] = []
    for et in ets:
        q = _stream_at(frame, et, transform)
        if q is not None:
            kept.append(et)
            stream.append(q)
    quats = np.asarray(stream).reshape(-1, 4)
    _canonicalise(quats)
    return np.asarray(kept), quats, len(ets) - len(kept)


def _stream_at(frame: str, et: float, transform: Transform | None) -> np.ndarray | None:
    """The stream's value at `et`, or None where SPICE does not resolve it."""
    try:
        q = spiceypy.m2q(spiceypy.pxform("J2000", frame, et))
    except spiceypy.exceptions.SpiceyError:
        return None
    return transform(et, q) if transform else q


def _canonicalise(quats: np.ndarray) -> None:
    """Flip each quaternion in place so adjacent samples differ by < 90°.

    Refinement signs each point against its segment start; a final pass keeps
    the whole stream continuous so SLERP picks the short arc everywhere.
    """
    for i in range(1, quats.shape[0]):
        if np.dot(quats[i], quats[i - 1]) < 0:
            quats[i] = -quats[i]
