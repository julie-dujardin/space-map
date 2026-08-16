"""Extract Chebyshev polynomial ephemeris from SPICE kernels for major bodies.

Ships position-only Chebyshev segments (parent-relative, ECLIPJ2000), chunked in
later export. Samples with spiceypy.spkezr and fits via numpy.polynomial.chebyshev,
picking sub-interval length and degree from each body's native SPK segment (read
with jplephem) to mirror the source kernel's accuracy/density tradeoff.

Passing "ECLIPJ2000" to spkezr does the ICRF → ecliptic rotation inside SPICE, so
coefficients are already in the frame the rest of the export uses.
"""

import logging
import math
from pathlib import Path

import numpy as np
import spiceypy
from jplephem.spk import SPK
from tqdm import tqdm

from space_map_data.models.object import ObjectType
from space_map_data.utils.time import S_PER_DAY, et_to_jd
from space_map_data.utils.naif import (
    CHEBYSHEV_ASTEROID_WHITELIST,
    CHEBYSHEV_MOON_WHITELIST,
    MajorBody,
)

logger = logging.getLogger(__name__)

# Cap coefficient count per segment to keep binary packing predictable.
_MAX_DEGREE = 20

# Core body types always get Chebyshev. Moons and asteroids are gated by
# explicit whitelists (surface-feature moons / shipped-asteroid set);
# everything else falls back to a cheaper mean-elements-plus-rates format
# exported separately.
_CORE_BODY_TYPES = frozenset(
    {
        ObjectType.star,
        ObjectType.planet,
        ObjectType.dwarf_planet,
        ObjectType.barycenter,
    }
)

# Interval-length floor for moons: source kernels like mar099/nep*xl ship with
# hour-scale native intervals (chosen for gravitational integration, not
# visualization). For a surface-feature body the orbital period is always ≥ a
# few hours, so a 0.5-day sub-interval still sits well below Nyquist for any
# whitelisted moon while cutting per-chunk size 2–5×. Error stays sub-km.
_MOON_MIN_INTLEN_S = 0.5 * S_PER_DAY

# Slow-moving bodies (planets, asteroids, barycenters) can share a kernel with
# fast-moving ones (e.g. Mars 499 lives in mar099.bsp alongside Phobos). The
# floor avoids inheriting those fast-sibling intervals.
_SLOW_BODY_MIN_INTLEN_S = 8 * S_PER_DAY


def _native_params(
    kernel_paths: list[Path], target_naif_id: int
) -> tuple[float, int] | None:
    """Find (sub-interval length in seconds, polynomial degree) from native SPK.

    Returns None if no Type-2/3 segment covering the target exists in any
    loaded kernel; uses the first match. `intlen` from jplephem is in days.
    """
    for path in kernel_paths:
        if path.suffix != ".bsp":
            continue
        try:
            spk = SPK.open(str(path))
        except Exception:
            logger.warning("Failed to open SPK %s; skipping", path, exc_info=True)
            continue
        try:
            for seg in spk.segments:
                if seg.target != target_naif_id:
                    continue
                if seg.data_type not in (2, 3):
                    continue
                _init_jd, intlen_days, coeffs = seg.load_array()
                intlen_s = float(intlen_days) * S_PER_DAY
                degree = int(coeffs.shape[2]) - 1
                return intlen_s, degree
        finally:
            spk.close()
    return None


def _cache_is_valid(
    path: Path,
    body: MajorBody,
    intlen_s: float,
    degree: int,
    start_et: float,
    end_et: float,
) -> bool:
    """Check whether the on-disk npz still matches the requested parameters.

    Invalidates on any change to parent, intlen, degree, or time range so we
    don't ship coefficients fit against a different configuration.
    """
    if not path.exists():
        return False
    try:
        with np.load(path) as data:
            meta = data["meta"]
            params = data["params"]
            coeffs_dtype = data["coeffs"].dtype
    except Exception:
        return False
    if meta.shape != (3,) or params.shape != (3,):
        return False
    # Stored coeffs must be float64 — the writer downcasts at pack time if
    # the destination zone is float32, but it needs the full-precision source
    # to make that choice.
    if coeffs_dtype != np.float64:
        return False
    if int(meta[0]) != body.naif_id:
        return False
    if int(meta[1]) != body.parent_id:
        return False
    if int(meta[2]) != degree:
        return False
    expected_start_jd = et_to_jd(start_et)
    expected_end_jd = et_to_jd(end_et)
    # JD-day comparisons need only sub-second precision; 1e-6 d ≈ 0.09 s.
    if abs(float(params[0]) - expected_start_jd) > 1e-6:
        return False
    if abs(float(params[1]) - expected_end_jd) > 1e-6:
        return False
    if abs(float(params[2]) - intlen_s) > 1e-6:
        return False
    return True


def _sample_body(
    naif_id: int,
    parent_id: int,
    start_et: float,
    end_et: float,
    intlen_s: float,
    degree: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Sample state vectors and fit Chebyshev per sub-interval, using
    Chebyshev-Lobatto nodes so the fit is an exact interpolant of degree
    `degree` from `degree+1` samples.

    Returns `(start_jds, end_jds, coeffs)`: sub-interval bounds in JD TDB, and
    `(n, 3, degree+1)` float64 coefficients for position in km, ECLIPJ2000,
    parent-relative — downcast to float32 later if the zone's
    `float64_coeffs` flag is off.
    """
    n_nodes = degree + 1
    k = np.arange(n_nodes)
    # Chebyshev–Lobatto extrema on [-1, 1]: x_k = cos(pi * k / N)
    nodes_tau = np.cos(np.pi * k / degree) if degree > 0 else np.zeros(1)

    n_intervals = int(math.ceil((end_et - start_et) / intlen_s))
    start_jds = np.empty(n_intervals, dtype=np.float64)
    end_jds = np.empty(n_intervals, dtype=np.float64)
    coeffs = np.empty((n_intervals, 3, n_nodes), dtype=np.float64)

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
        # Chebyshev extrema this is an exact interpolant). Stored at full
        # float64 precision — the per-zone writer chooses whether to truncate
        # to float32 when packing the binary.
        for axis in range(3):
            coeffs[i, axis, :] = np.polynomial.chebyshev.chebfit(
                nodes_tau, positions[:, axis], degree
            )

        start_jds[i] = et_to_jd(seg_start_et)
        end_jds[i] = et_to_jd(seg_end_et)

    return start_jds, end_jds, coeffs


def _should_extract(body: MajorBody) -> bool:
    """Decide whether this body is worth shipping Chebyshev for.

    Core body types anchor the hierarchical frame and are always included.
    Moons and asteroids are gated by explicit whitelists (surface-feature
    moons; the 15 main-belt perturbers shipped before sb441-n373.bsp).
    Everything else falls back to the cheaper mean-elements format.
    """
    if body.naif_id == 0:
        return False  # SSB is the coordinate origin — no orbit to describe
    if body.object_type in _CORE_BODY_TYPES:
        return True
    if body.object_type == ObjectType.moon:
        name_lc = (body.name or "").lower()
        return name_lc in CHEBYSHEV_MOON_WHITELIST
    if body.object_type == ObjectType.asteroid:
        return body.naif_id in CHEBYSHEV_ASTEROID_WHITELIST
    return False


def extract_chebyshev(
    cheb_dir: Path,
    bodies: list[MajorBody],
    kernel_paths: list[Path],
    start_year: int,
    end_year: int,
) -> int:
    """Extract Chebyshev ephemeris for every body in `bodies` that we want to ship.

    Writes one `.npz` per body under `cheb_dir/{naif_id}.npz`, skipping bodies whose
    cache already matches; stale files are removed at the end so the directory always
    reflects the current filter policy. Caller must have furnished all relevant
    kernels before invoking. Returns the number of bodies present after the run.
    """
    cheb_dir.mkdir(parents=True, exist_ok=True)

    start_et = spiceypy.str2et(f"{start_year}-01-01T00:00:00")
    end_et = spiceypy.str2et(f"{end_year}-01-01T00:00:00")
    logger.info(
        "Extracting Chebyshev ephemeris: %d → %d (%.1f days covered)",
        start_year,
        end_year,
        (end_et - start_et) / S_PER_DAY,
    )

    # Plan first so we can report the work split (extract vs. cache vs. skip)
    # before the sampling progress bar starts — sampling dominates wall time,
    # so an up-front summary lets the operator know whether this run is mostly
    # cached or mostly cold.
    to_extract: list[tuple[MajorBody, float, int, Path]] = []
    cached = 0
    skipped_no_spk = 0
    skipped_filter = 0
    kept_paths: set[Path] = set()
    for body in bodies:
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

        if (
            body.object_type in _CORE_BODY_TYPES
            or body.object_type == ObjectType.asteroid
        ):
            # Source kernel's fine interval was chosen for a fast sibling
            # (typical case: Mars 499 in a kernel sized for Phobos). Use the
            # core floor to avoid generating ~100× more segments than needed.
            # Asteroids share the floor: they're slow main-belt movers, no
            # value in segments shorter than 8 days.
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

        out_path = cheb_dir / f"{body.naif_id}.npz"
        if _cache_is_valid(out_path, body, intlen_s, degree, start_et, end_et):
            kept_paths.add(out_path)
            cached += 1
            continue

        to_extract.append((body, intlen_s, degree, out_path))

    logger.info(
        "Chebyshev plan: %d to extract, %d reused from cache, %d skipped "
        "(no SPK coverage), %d skipped (filtered out)",
        len(to_extract),
        cached,
        skipped_no_spk,
        skipped_filter,
    )

    extracted = 0
    for body, intlen_s, degree, out_path in tqdm(
        to_extract, desc="Chebyshev", unit="body"
    ):
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

        np.savez(
            out_path,
            start_jds=start_jds,
            end_jds=end_jds,
            coeffs=coeffs,
            meta=np.array(
                [body.naif_id, body.parent_id, degree],
                dtype=np.int64,
            ),
            params=np.array(
                [et_to_jd(start_et), et_to_jd(end_et), intlen_s],
                dtype=np.float64,
            ),
        )
        kept_paths.add(out_path)
        extracted += 1

    removed_stale = 0
    for existing in cheb_dir.glob("*.npz"):
        if existing not in kept_paths:
            existing.unlink()
            removed_stale += 1

    logger.info(
        "Chebyshev extraction complete: %d bodies extracted, %d reused from "
        "cache, %d skipped (no SPK coverage), %d skipped (filtered out), "
        "%d stale files removed -> %s",
        extracted,
        cached,
        skipped_no_spk,
        skipped_filter,
        removed_stale,
        cheb_dir,
    )
    return extracted + cached
