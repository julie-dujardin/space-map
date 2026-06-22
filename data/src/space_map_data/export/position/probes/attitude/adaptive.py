"""Adaptive geodesic sampling of a CK attitude window.

Replaces uniform oversampling. A fixed cadence either aliases fast motion
(a slew or spin between samples is missed) or wastes millions of samples on
geodesic cruise. Instead we seed a coarse grid, then recursively subdivide
any segment whose interior truth deviates from the SLERP of its endpoints by
more than the error budget — probing several interior points so a maneuver
shorter than the seed gap can't slip through on a lucky midpoint.

Output is a faithful (non-aliased) sample stream in *stream space*: raw
J2000->body, or the spin-baseline residual when `transform` is given. A
separate `extract_keyframes` pass then decimates the geodesic runs the seed
grid leaves behind.
"""

from collections.abc import Callable

import numpy as np
import spiceypy

from .quaternion import angle_between, slerp

# Coarse seed cadence (s). Fine enough to keep an un-baselined spinner under
# half a turn per segment (so refinement can't alias), coarse enough that
# cruise costs few pxform calls. Fast spinners are removed by the baseline
# first, so their residual is slow and this cadence is safe.
SEED_DT_S = 300.0
# Refinement floor — stop subdividing below this even if still out of budget.
MIN_DT_S = 1.0
# Interior probe fractions per segment. Three points bound the largest
# unprobed gap at a quarter of the segment, catching brief slews.
PROBE_FRACS = (0.25, 0.5, 0.75)

_IDENTITY = np.array([1.0, 0.0, 0.0, 0.0])

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
) -> tuple[np.ndarray, np.ndarray, int]:
    """Sample `[t0, t1]` adaptively → ascending `(ets, quats, n_gaps)`.

    `transform(et, q_raw)` maps raw J2000->body truth to the stream we keyframe
    (the baseline residual); identity when None. Quats are sign-canonicalised
    continuously so downstream SLERP and smallest-three packing stay smooth.
    `n_gaps` is the count of samples that fell in a CK gap (last good repeated)
    — the caller aggregates it into one log line per probe instead of per file.
    """
    last_raw: list[np.ndarray] = [_IDENTITY]
    gaps = [0]

    def truth(et: float) -> np.ndarray:
        try:
            q = spiceypy.m2q(spiceypy.pxform("J2000", frame, float(et)))
            last_raw[0] = q
        except spiceypy.exceptions.SpiceyError:
            gaps[0] += 1
            q = last_raw[0]  # repeat last good across the gap
        return transform(et, q) if transform else q

    n_seed = max(2, int(round((t1 - t0) / seed_dt)) + 1)
    grid = np.linspace(t0, t1, n_seed)
    seed_q = [truth(float(grid[0]))]
    for i in range(1, n_seed):
        seed_q.append(truth(float(grid[i])))

    out_t: list[float] = [float(grid[0])]
    out_q: list[np.ndarray] = [seed_q[0]]

    def refine(
        ta: float, qa: np.ndarray, tb: float, qb: np.ndarray, depth: int
    ) -> None:
        if tb - ta <= min_dt or depth > 40:
            return
        worst_f, worst_err, worst_q = 0.5, -1.0, qa
        for f in PROBE_FRACS:
            tf = ta + f * (tb - ta)
            qf = truth(tf)
            err = angle_between(slerp(qa, qb, f), qf)
            if err > worst_err:
                worst_f, worst_err, worst_q = f, err, qf
        if worst_err <= eps_rad:
            return
        tm = ta + worst_f * (tb - ta)
        refine(ta, qa, tm, worst_q, depth + 1)
        out_t.append(tm)
        out_q.append(worst_q)
        refine(tm, worst_q, tb, qb, depth + 1)

    for i in range(1, n_seed):
        refine(float(grid[i - 1]), seed_q[i - 1], float(grid[i]), seed_q[i], 0)
        out_t.append(float(grid[i]))
        out_q.append(seed_q[i])

    quats = np.asarray(out_q)
    _canonicalise(quats)
    return np.asarray(out_t), quats, gaps[0]


def _canonicalise(quats: np.ndarray) -> None:
    """Flip each quaternion in place so adjacent samples differ by < 90°.

    Refinement signs each point against its segment start; a final pass keeps
    the whole stream continuous so SLERP picks the short arc everywhere.
    """
    for i in range(1, quats.shape[0]):
        if np.dot(quats[i], quats[i - 1]) < 0:
            quats[i] = -quats[i]
