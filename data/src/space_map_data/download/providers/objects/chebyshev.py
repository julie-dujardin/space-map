"""Extract Chebyshev polynomial ephemeris from SPICE kernels for major bodies.

Ships position-only Chebyshev segments (parent-relative, ECLIPJ2000) covering a
configurable time range, chunked in later export. Samples positions with
spiceypy.spkezr and fits via numpy.polynomial.chebyshev — picking each body's
sub-interval length and polynomial degree from the native SPK segment (read with
jplephem) so we mirror the source kernel's accuracy/density tradeoff.

Frame note: we pass "ECLIPJ2000" to spkezr, so the rotation from ICRF → ecliptic
happens inside SPICE and the coefficients are already in the frame the rest of
the export uses.
"""

import logging
import math
from pathlib import Path

import numpy as np
import spiceypy
from jplephem.spk import SPK
from tqdm import tqdm

from space_map_data.models.object import ObjectType
from space_map_data.utils.naif import CHEBYSHEV_MOON_WHITELIST, MajorBody

logger = logging.getLogger(__name__)

_S_PER_DAY = 86400.0
_J2000_JD = 2451545.0

# Cap coefficient count per segment to keep binary packing predictable.
_MAX_DEGREE = 20

# Core body types always get Chebyshev. Moons are gated by an explicit whitelist
# (surface-feature bodies only); everything else falls back to a cheaper
# mean-elements-plus-rates format exported separately.
_CORE_BODY_TYPES = frozenset(
    {
        ObjectType.star,
        ObjectType.planet,
        ObjectType.dwarf_planet,
        ObjectType.barycenter,
        ObjectType.asteroid,
    }
)

# Interval-length floor for moons: source kernels like mar099/nep*xl ship with
# hour-scale native intervals (chosen for gravitational integration, not
# visualization). For a surface-feature body the orbital period is always ≥ a
# few hours, so a 0.5-day sub-interval still sits well below Nyquist for any
# whitelisted moon while cutting per-chunk size 2–5×. Error stays sub-km.
_MOON_MIN_INTLEN_S = 0.5 * _S_PER_DAY

# Slow-moving bodies (planets, asteroids, barycenters) can share a kernel with
# fast-moving ones (e.g. Mars 499 lives in mar099.bsp alongside Phobos). The
# floor avoids inheriting those fast-sibling intervals.
_SLOW_BODY_MIN_INTLEN_S = 8 * _S_PER_DAY


def _et_to_jd(et: float) -> float:
    """SPICE ET (TDB seconds past J2000) → Julian Date TDB."""
    return _J2000_JD + et / _S_PER_DAY


def _native_params(
    kernel_paths: list[Path], target_naif_id: int
) -> tuple[float, int] | None:
    """Find (sub-interval length in seconds, polynomial degree) from native SPK.

    jplephem returns segment data with shape `(3, n_records, n_coefficients)`
    for Type-2 (position-only) and `(6, …)` for Type-3 (position+velocity);
    `intlen` is in days.

    Returns None if no Type-2/3 segment covering the target exists in any
    loaded kernel. Uses the first match.
    """
    for path in kernel_paths:
        if path.suffix != ".bsp":
            continue
        try:
            spk = SPK.open(str(path))
        except Exception:
            continue
        try:
            for seg in spk.segments:
                if seg.target != target_naif_id:
                    continue
                if seg.data_type not in (2, 3):
                    continue
                _init_jd, intlen_days, coeffs = seg.load_array()
                intlen_s = float(intlen_days) * _S_PER_DAY
                degree = int(coeffs.shape[2]) - 1
                return intlen_s, degree
        finally:
            spk.close()
    return None


def _sample_body(
    naif_id: int,
    parent_id: int,
    start_et: float,
    end_et: float,
    intlen_s: float,
    degree: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Sample state vectors and fit Chebyshev per sub-interval.

    Uses Chebyshev–Lobatto nodes (extrema) so the fit is an exact interpolant
    of degree `degree` from `degree+1` samples.

    Returns
    -------
    start_jds : (n,) float64  — sub-interval start, JD TDB
    end_jds   : (n,) float64  — sub-interval end, JD TDB
    coeffs    : (n, 3, degree+1) float32  — Chebyshev coefficients (c0..cN) for
                                            position in km, ECLIPJ2000,
                                            parent-relative
    """
    n_nodes = degree + 1
    k = np.arange(n_nodes)
    # Chebyshev–Lobatto extrema on [-1, 1]: x_k = cos(pi * k / N)
    nodes_tau = np.cos(np.pi * k / degree) if degree > 0 else np.zeros(1)

    n_intervals = int(math.ceil((end_et - start_et) / intlen_s))
    start_jds = np.empty(n_intervals, dtype=np.float64)
    end_jds = np.empty(n_intervals, dtype=np.float64)
    coeffs = np.empty((n_intervals, 3, n_nodes), dtype=np.float32)

    target_str = str(naif_id)
    parent_str = str(parent_id)

    for i in range(n_intervals):
        seg_start_et = start_et + i * intlen_s
        seg_end_et = min(seg_start_et + intlen_s, end_et)
        mid = 0.5 * (seg_start_et + seg_end_et)
        half = 0.5 * (seg_end_et - seg_start_et)
        sample_ets = mid + half * nodes_tau

        positions = np.empty((n_nodes, 3), dtype=np.float64)
        for j, et in enumerate(sample_ets):
            state, _ = spiceypy.spkezr(target_str, et, "ECLIPJ2000", "NONE", parent_str)
            positions[j, 0] = state[0]
            positions[j, 1] = state[1]
            positions[j, 2] = state[2]

        # Fit per axis (chebfit uses least-squares; with node-count == deg+1 at
        # Chebyshev extrema this is an exact interpolant).
        for axis in range(3):
            c = np.polynomial.chebyshev.chebfit(nodes_tau, positions[:, axis], degree)
            coeffs[i, axis, :] = c.astype(np.float32)

        start_jds[i] = _et_to_jd(seg_start_et)
        end_jds[i] = _et_to_jd(seg_end_et)

    return start_jds, end_jds, coeffs


def _should_extract(body: MajorBody) -> bool:
    """Decide whether this body is worth shipping Chebyshev for.

    Core body types (star, planets, dwarves, barycenters, asteroids) are always
    included — they anchor the hierarchical frame or carry named-asteroid
    trajectories. Moons are gated by an explicit name whitelist of
    surface-feature bodies (Io, Enceladus, Titan, …): those are the only moons
    a user ever zooms into, and the rest get the much cheaper mean-elements
    format exported separately.
    """
    if body.naif_id == 0:
        return False  # SSB is the coordinate origin — no orbit to describe
    if body.object_type in _CORE_BODY_TYPES:
        return True
    if body.object_type == ObjectType.moon:
        name_lc = (body.name or "").lower()
        return name_lc in CHEBYSHEV_MOON_WHITELIST
    return False


def extract_chebyshev(
    out_dir: Path,
    bodies: list[MajorBody],
    kernel_paths: list[Path],
    start_year: int,
    end_year: int,
) -> int:
    """Extract Chebyshev ephemeris for every body in `bodies` that we want to
    ship.

    Writes one `.npz` per body under `out_dir / chebyshev / {naif_id}.npz`.
    Stale files from a prior run are removed first so the directory always
    reflects the current filter policy.

    Returns the number of bodies successfully extracted.

    Caller must have furnished all relevant kernels before invoking; we only
    read the SPK files here to discover native sub-interval parameters.
    """
    import shutil

    cheb_dir = out_dir / "chebyshev"
    if cheb_dir.exists():
        shutil.rmtree(cheb_dir)
    cheb_dir.mkdir(exist_ok=True)

    start_et = spiceypy.str2et(f"{start_year}-01-01T00:00:00")
    end_et = spiceypy.str2et(f"{end_year}-01-01T00:00:00")
    logger.info(
        "Extracting Chebyshev ephemeris: %d → %d (%.1f days covered)",
        start_year,
        end_year,
        (end_et - start_et) / _S_PER_DAY,
    )

    extracted = 0
    skipped_no_spk = 0
    skipped_filter = 0
    for body in tqdm(bodies, desc="Chebyshev", unit="body"):
        native = _native_params(kernel_paths, body.naif_id)
        if native is None:
            # No raw SPK segment — e.g. the body is classified as a moon/planet
            # but isn't actually in any loaded kernel. Skip rather than
            # fabricate defaults: we wouldn't get valid positions anyway.
            skipped_no_spk += 1
            continue

        intlen_s, degree = native
        if not _should_extract(body):
            skipped_filter += 1
            continue

        if body.object_type in _CORE_BODY_TYPES:
            # Source kernel's fine interval was chosen for a fast sibling
            # (typical case: Mars 499 in a kernel sized for Phobos). Use the
            # core floor to avoid generating ~100× more segments than needed.
            intlen_s = max(intlen_s, _SLOW_BODY_MIN_INTLEN_S)
        elif body.object_type == ObjectType.moon:
            # Moon whitelist members get a 0.5-day floor; native intervals as
            # short as 0.1 d (Puck, Proteus) otherwise quadruple segment count
            # without visible precision gain at visualization zoom.
            intlen_s = max(intlen_s, _MOON_MIN_INTLEN_S)
        if degree > _MAX_DEGREE:
            logger.warning(
                "%s (%d): native degree %d exceeds cap %d; clamping",
                body.name,
                body.naif_id,
                degree,
                _MAX_DEGREE,
            )
            degree = _MAX_DEGREE

        try:
            start_jds, end_jds, coeffs = _sample_body(
                body.naif_id,
                body.parent_id,
                start_et,
                end_et,
                intlen_s,
                degree,
            )
        except spiceypy.exceptions.SpiceyError as e:
            logger.warning(
                "Chebyshev sampling failed for %s (%d): %s",
                body.name,
                body.naif_id,
                e,
            )
            continue

        out_path = cheb_dir / f"{body.naif_id}.npz"
        np.savez(
            out_path,
            start_jds=start_jds,
            end_jds=end_jds,
            coeffs=coeffs,
            meta=np.array(
                [body.naif_id, body.parent_id, degree],
                dtype=np.int64,
            ),
        )
        extracted += 1

    logger.info(
        "Chebyshev extraction complete: %d bodies extracted, %d skipped "
        "(no SPK coverage), %d skipped (filtered out) -> %s",
        extracted,
        skipped_no_spk,
        skipped_filter,
        cheb_dir,
    )
    return extracted
