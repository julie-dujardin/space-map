"""Per-chunk sizing for probe trajectories.

For each (probe, zone, chunk) the pipeline picks one of two formats:

  * Method-C Kepler (cheap): osculating a/e/i + linearly-drifting Ω/ω/M.
    Constant-size payload regardless of chunk length: 9 float32 = 36 bytes.

  * Chebyshev (accurate): per-sub-interval polynomial coefficients in the
    same packing as `download/providers/objects/chebyshev.py`. Cost scales
    with the sub-interval length picked from a sweep — coarsest one that
    keeps max position error below the zone's accuracy threshold.

The decision is per-chunk so a probe naturally switches methods over time:
Kepler during cruise / steady orbit, Chebyshev across flybys, EDLs, and
maneuver-heavy windows.
"""

import logging
import math
from dataclasses import dataclass

import numpy as np
import spiceypy

from space_map_data.probes.zones import Zone, threshold_for

logger = logging.getLogger(__name__)

_S_PER_DAY = 86400.0
_J2000_JD = 2451545.0
_AU_KM = 149_597_870.7

# Sub-interval sweep, coarsest first. We pick the largest intlen whose max
# position error stays under the zone threshold.
INTLEN_SWEEP_DAYS: tuple[float, ...] = (30.0, 10.0, 3.0, 1.0, 0.3, 0.1, 0.03)
CHEBYSHEV_DEGREE = 11


def _chebyshev_bytes_per_segment(float64_coeffs: bool) -> int:
    """16 B header (two float64 JDs) + 3 axes × (degree+1) coefficients."""
    coeff_bytes = 8 if float64_coeffs else 4
    return 16 + 3 * (CHEBYSHEV_DEGREE + 1) * coeff_bytes


def _kepler_bytes(float64_coeffs: bool) -> int:
    """9 Kepler elements (a, e, i, Ω₀, Ω̇, ω₀, ω̇, M₀, n)."""
    return 9 * (8 if float64_coeffs else 4)


# Method-C fit samples per chunk for both the fit and the accuracy check.
SAMPLES_PER_CHUNK = 50
# How wide a window to draw Method-C samples from. Wider window captures
# long-period secular trends but assumes the orbit is well-approximated by
# linear drift over the window. ±0.5y is a reasonable middle ground for
# spacecraft (vs ±5y for natural moons whose perturbations are tiny).
METHOD_C_HALF_WINDOW_S = 0.5 * 365.25 * _S_PER_DAY


@dataclass(frozen=True)
class SubChunkSizing:
    """One Kepler sub-chunk: short enough that Method-C error stays below
    threshold, or escalated to Chebyshev for that interval if it doesn't."""

    method: str  # "kepler" | "chebyshev" | "uncoverable"
    bytes: int
    max_err_km: float
    detail: str  # extra context (intlen for chebyshev, fit-residual for kepler)


@dataclass(frozen=True)
class ChunkSizing:
    """Aggregate of all sub-chunks inside one streaming chunk."""

    total_bytes: int
    n_kepler: int
    n_chebyshev: int
    n_uncoverable: int
    max_err_km: float
    sub_chunks: list[SubChunkSizing]


def _safe_spkezr(
    target: int, et: float, frame: str, center: int
) -> tuple[np.ndarray, float] | None:
    """`spkezr` wrapped to return None on SPICE failure instead of raising."""
    try:
        state, lt = spiceypy.spkezr(str(target), et, frame, "NONE", str(center))
    except spiceypy.exceptions.SpiceyError:
        return None
    return np.asarray(state), float(lt)


_MIN_VALID_SAMPLE_FRACTION = 0.5


def _fit_method_c(
    naif_id: int,
    fit_center_naif_id: int,
    mu: float,
    sample_ets: np.ndarray,
) -> list[dict] | None:
    """Fit Method-C: snapshot elements at the fit-window midpoint + linear
    drift rates from the rest of the samples.

    Strategy:
      * Take the osculating elements at the sample closest to the window
        midpoint as (a, e, i, om₀, w₀, m₀). Snapshot avoids the averaging
        bias that plagues cruise probes whose `a` drifts across mid-cruise
        TCMs (one TCM shifts a by ~0.1%, and 0.1% of 1 AU is 180,000 km of
        position error if you average instead of snapshot).
      * Linear-fit (om(t), w(t), M(t)) across ALL valid samples to recover
        secular drift rates Ω̇, ω̇, n. Snapshot anchors position; drift fit
        captures evolution.

    Samples that come back hyperbolic (e ≥ 1, e.g. at planet flyby
    periapsis) are skipped — we fit on the remaining ones. Returns None
    when fewer than half the samples are usable OR no valid sample exists
    near the midpoint.
    """
    valid_ts: list[float] = []
    a_list: list[float] = []
    e_list: list[float] = []
    i_list: list[float] = []
    om_list: list[float] = []
    w_list: list[float] = []
    m_list: list[float] = []

    for et in sample_ets:
        s = _safe_spkezr(naif_id, float(et), "ECLIPJ2000", fit_center_naif_id)
        if s is None:
            continue
        state, _ = s
        try:
            elts = spiceypy.oscelt(state, float(et), mu)
        except spiceypy.exceptions.SpiceyError:
            continue
        rp, ecc, inc, lnode, argp, m0_at_t, _t0, _mu = elts
        if ecc >= 1.0 or rp <= 0:
            continue  # hyperbolic outlier — skip, fit the bound rest
        valid_ts.append(float(et))
        a_list.append(rp / (1 - ecc))
        e_list.append(ecc)
        i_list.append(inc)
        om_list.append(lnode)
        w_list.append(argp)
        m_list.append(m0_at_t)

    if len(valid_ts) < max(10, int(_MIN_VALID_SAMPLE_FRACTION * len(sample_ets))):
        return None

    t_mid = 0.5 * (float(sample_ets[0]) + float(sample_ets[-1]))
    valid_ts_arr = np.asarray(valid_ts)

    snap_idx = int(np.argmin(np.abs(valid_ts_arr - t_mid)))
    t_snap = valid_ts[snap_idx]
    if a_list[snap_idx] <= 0:
        return None

    base = {
        "a_km": a_list[snap_idx],
        "e": e_list[snap_idx],
        "i_rad": i_list[snap_idx],
        "om0": om_list[snap_idx],
        "w0": w_list[snap_idx],
        "m0": m_list[snap_idx],
        "mu": mu,
        "t_mid": t_snap,
    }

    # --- "Pure" variant: snapshot only, conics propagates M via mu. ---
    # Best for clean cruise: fit-window TCMs / perturbations don't bias the
    # propagation, and pure Kepler is the right model when no J2 source
    # exists (heliocentric).
    pure = {**base, "om_dot": 0.0, "w_dot": 0.0, "n_mean_rad_s": 0.0, "mode": "pure"}

    # --- "Drift" variant: linear-fit Ω̇, ω̇, n_mean over the sample window. ---
    # Best for J2-perturbed orbits — MAVEN-class probes drop from 159 km
    # worst-day error to 21 km with drift on. We use the *fitted* mean
    # motion (rather than sqrt(mu/a³)) so any J2 Ṁ correction is captured.
    times_rel = valid_ts_arr - t_snap
    om_un = np.unwrap(np.asarray(om_list))
    w_un = np.unwrap(np.asarray(w_list))
    m_un = np.unwrap(np.asarray(m_list))
    om_dot, _ = np.polyfit(times_rel, om_un, 1)
    w_dot, _ = np.polyfit(times_rel, w_un, 1)
    n_mean, _ = np.polyfit(times_rel, m_un, 1)
    if n_mean <= 0:
        return [pure]  # only the pure variant is usable
    drift = {
        **base,
        "om_dot": float(om_dot),
        "w_dot": float(w_dot),
        "n_mean_rad_s": float(n_mean),
        "mode": "drift",
    }
    return [pure, drift]


def _kepler_state_at(elts: dict, et: float) -> np.ndarray | None:
    """Evaluate a Method-C variant at `et`, returning position (km).

    Two modes:
      * `pure`: snapshot at t_snap, conics propagates M via `mu` (no drift).
      * `drift`: snapshot + linear-fit drift in (Ω, ω, M). M is computed
        manually so we honor the J2 Ṁ correction baked into the fitted
        mean motion; we pass `t0=et` to conics so it doesn't re-propagate.
    """
    dt = et - elts["t_mid"]
    om_t = elts["om0"] + elts["om_dot"] * dt
    w_t = elts["w0"] + elts["w_dot"] * dt
    a = elts["a_km"]
    e = elts["e"]
    rp = a * (1 - e)
    if elts.get("mode") == "drift":
        m_t = elts["m0"] + elts["n_mean_rad_s"] * dt
        t0_for_conics = et  # no further propagation; we've already drifted M
    else:
        m_t = elts["m0"]  # at t_snap
        t0_for_conics = elts["t_mid"]
    elts_array = np.array(
        [rp, e, elts["i_rad"], om_t, w_t, m_t, t0_for_conics, elts["mu"]],
        dtype=np.float64,
    )
    try:
        state = spiceypy.conics(elts_array, et)
    except spiceypy.exceptions.SpiceyError:
        return None
    return state[:3]


def _kepler_max_err_km(
    elts: dict[str, float],
    naif_id: int,
    fit_center_naif_id: int,
    eval_ets: np.ndarray,
) -> float:
    """Compare fit against SPICE truth at `eval_ets`, return max km error."""
    max_err = 0.0
    for et in eval_ets:
        truth = _safe_spkezr(naif_id, float(et), "ECLIPJ2000", fit_center_naif_id)
        if truth is None:
            continue
        fitted = _kepler_state_at(elts, float(et))
        if fitted is None:
            return float("inf")
        err = float(np.linalg.norm(fitted - truth[0][:3]))
        if err > max_err:
            max_err = err
    return max_err


def _chebyshev_sub_interval_count(intlen_s: float, chunk_s: float) -> int:
    return max(1, int(math.ceil(chunk_s / intlen_s)))


def _chebyshev_eval_err_km(
    naif_id: int,
    fit_center_naif_id: int,
    t_start: float,
    t_end: float,
    intlen_s: float,
    n_eval_samples: int = 40,
) -> float:
    """Refit Chebyshev for one chunk at `intlen_s`, evaluate max km error.

    Implements the same polynomial fit as `chebyshev._sample_body` but only
    keeps the residual: we never write coefficients to disk for sizing runs.
    """
    n_nodes = CHEBYSHEV_DEGREE + 1
    k = np.arange(n_nodes)
    nodes_tau = (
        np.cos(np.pi * k / CHEBYSHEV_DEGREE) if CHEBYSHEV_DEGREE > 0 else np.zeros(1)
    )

    # Pre-sample SPICE truth densely so we can evaluate residuals after fit.
    eval_ets = np.linspace(t_start, t_end, n_eval_samples)
    truth = np.empty((n_eval_samples, 3))
    for j, et in enumerate(eval_ets):
        s = _safe_spkezr(naif_id, float(et), "ECLIPJ2000", fit_center_naif_id)
        if s is None:
            return float("inf")
        truth[j] = s[0][:3]

    n_segments = _chebyshev_sub_interval_count(intlen_s, t_end - t_start)
    seg_starts = t_start + np.arange(n_segments) * intlen_s
    seg_ends = np.minimum(seg_starts + intlen_s, t_end)

    # For each evaluation time, find which segment it falls in and evaluate
    # the segment's Chebyshev polynomial. We fit segments lazily — only those
    # an eval point falls into.
    seg_polys: dict[int, list[np.ndarray]] = {}  # seg_idx -> [coeffs per axis]
    max_err = 0.0
    for j, et in enumerate(eval_ets):
        seg_idx = int(
            np.clip(np.searchsorted(seg_ends, et, side="left"), 0, n_segments - 1)
        )
        if seg_idx not in seg_polys:
            seg_start = seg_starts[seg_idx]
            seg_end = seg_ends[seg_idx]
            mid = 0.5 * (seg_start + seg_end)
            half = 0.5 * (seg_end - seg_start)
            sample_ets = mid + half * nodes_tau
            positions = np.empty((n_nodes, 3))
            for ii, samp_et in enumerate(sample_ets):
                s = _safe_spkezr(
                    naif_id, float(samp_et), "ECLIPJ2000", fit_center_naif_id
                )
                if s is None:
                    return float("inf")
                positions[ii] = s[0][:3]
            polys = [
                np.polynomial.chebyshev.chebfit(
                    nodes_tau, positions[:, axis], CHEBYSHEV_DEGREE
                )
                for axis in range(3)
            ]
            seg_polys[seg_idx] = polys
        seg_start = seg_starts[seg_idx]
        seg_end = seg_ends[seg_idx]
        mid = 0.5 * (seg_start + seg_end)
        half = 0.5 * (seg_end - seg_start)
        tau = (et - mid) / half
        fitted = np.array(
            [
                np.polynomial.chebyshev.chebval(tau, seg_polys[seg_idx][axis])
                for axis in range(3)
            ]
        )
        err = float(np.linalg.norm(fitted - truth[j]))
        if err > max_err:
            max_err = err
    return max_err


def _size_sub_chunk(
    naif_id: int,
    zone: Zone,
    mu: float,
    sub_t_start: float,
    sub_t_end: float,
    base_threshold_km: float,
) -> SubChunkSizing:
    """Pick Kepler vs Chebyshev for one sub-chunk.

    Tries both Method-C variants (pure-Kepler-from-snapshot, drift-fitted)
    and keeps whichever has lower max-err on the sub-chunk. The Chebyshev
    sweep is reserved for cases where Kepler exceeds the (possibly relaxed)
    threshold.

    `base_threshold_km` is the zone default. If the probe's orbital period
    inferred from the fit is below the zone's short-orbit cutoff, the
    threshold is relaxed to `zone.short_orbit_threshold_km` (~200 km for
    planetary). Phase-shift visible at deep zoom but invisible at the
    typical planet-system view.
    """
    sub_s = sub_t_end - sub_t_start
    sub_mid = 0.5 * (sub_t_start + sub_t_end)
    kepler_bytes = _kepler_bytes(zone.float64_coeffs)
    cheb_bytes_per_seg = _chebyshev_bytes_per_segment(zone.float64_coeffs)

    fit_half_s = max(2.0 * sub_s, 2 * _S_PER_DAY)
    fit_ets = np.linspace(sub_mid - fit_half_s, sub_mid + fit_half_s, 80)
    variants = _fit_method_c(naif_id, zone.fit_center_naif_id, mu, fit_ets)

    kepler_err = float("inf")
    if variants:
        eval_ets = np.linspace(sub_t_start, sub_t_end, 20)
        best_v: tuple[dict, float] | None = None
        for v in variants:
            err = _kepler_max_err_km(v, naif_id, zone.fit_center_naif_id, eval_ets)
            if best_v is None or err < best_v[1]:
                best_v = (v, err)
        if best_v is not None:
            kepler_err = best_v[1]
            # Threshold relaxation for short-period orbits.
            period_s = 2 * math.pi * math.sqrt(best_v[0]["a_km"] ** 3 / mu)
            threshold_km = (
                max(base_threshold_km, zone.short_orbit_threshold_km)
                if period_s < zone.short_orbit_period_s
                else base_threshold_km
            )
            if kepler_err <= threshold_km:
                return SubChunkSizing(
                    method="kepler",
                    bytes=kepler_bytes,
                    max_err_km=kepler_err,
                    detail=f"{best_v[0]['mode']} thresh={threshold_km:.0f}km",
                )
        else:
            threshold_km = base_threshold_km
    else:
        threshold_km = base_threshold_km

    # Chebyshev fallback.
    best: tuple[float, float, int] | None = None
    for intlen_d in INTLEN_SWEEP_DAYS:
        intlen_s = intlen_d * _S_PER_DAY
        seg_s = min(intlen_s, sub_s)
        n_segments = _chebyshev_sub_interval_count(seg_s, sub_s)
        err = _chebyshev_eval_err_km(
            naif_id, zone.fit_center_naif_id, sub_t_start, sub_t_end, seg_s
        )
        bytes_ = n_segments * cheb_bytes_per_seg
        if math.isinf(err) or math.isnan(err):
            return SubChunkSizing(
                "uncoverable", 0, float("nan"), "spkezr failed mid-sub-chunk"
            )
        if err <= threshold_km:
            return SubChunkSizing(
                method="chebyshev",
                bytes=bytes_,
                max_err_km=err,
                detail=f"intlen={intlen_d}d kepler_err={kepler_err:.1g}km",
            )
        if best is None or err < best[1]:
            best = (intlen_d, err, bytes_)

    if best is None:
        return SubChunkSizing("uncoverable", 0, float("nan"), "no fits possible")
    return SubChunkSizing(
        method="chebyshev",
        bytes=best[2],
        max_err_km=best[1],
        detail=f"intlen={best[0]}d OVER_THRESH",
    )


def size_chunk(
    naif_id: int,
    zone: Zone,
    t_start: float,
    t_end: float,
) -> ChunkSizing:
    """Slice the streaming chunk into Kepler-width sub-chunks, fit each.

    Each sub-chunk decides independently between Method-C Kepler (cheap:
    9 floats = 36 bytes) and Chebyshev (refit-and-pack like
    `download/providers/objects/chebyshev.py`). The overall chunk's byte
    cost is the sum of its sub-chunks.
    """
    try:
        mu = spiceypy.bodvrd(str(zone.fit_center_naif_id), "GM", 1)[1][0]
    except spiceypy.exceptions.SpiceyError:
        return ChunkSizing(0, 0, 0, 1, float("inf"), [])

    base_threshold_km = threshold_for(zone, naif_id)
    sub_s = zone.kepler_subchunk_days * _S_PER_DAY

    sub_chunks: list[SubChunkSizing] = []
    cur = t_start
    while cur < t_end:
        nxt = min(cur + sub_s, t_end)
        sub_chunks.append(
            _size_sub_chunk(naif_id, zone, mu, cur, nxt, base_threshold_km)
        )
        cur = nxt

    n_kepler = sum(1 for s in sub_chunks if s.method == "kepler")
    n_chebyshev = sum(1 for s in sub_chunks if s.method == "chebyshev")
    n_uncoverable = sum(1 for s in sub_chunks if s.method == "uncoverable")
    finite_errs = [s.max_err_km for s in sub_chunks if math.isfinite(s.max_err_km)]
    return ChunkSizing(
        total_bytes=sum(s.bytes for s in sub_chunks),
        n_kepler=n_kepler,
        n_chebyshev=n_chebyshev,
        n_uncoverable=n_uncoverable,
        max_err_km=max(finite_errs, default=0.0),
        sub_chunks=sub_chunks,
    )
