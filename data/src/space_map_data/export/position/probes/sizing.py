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
from dataclasses import dataclass, field

import numpy as np
import spiceypy

from space_map_data.probes.zones import Zone, threshold_for
from space_map_data.utils.time import S_PER_DAY

logger = logging.getLogger(__name__)

_AU_KM = 149_597_870.7

# Sub-interval sweep, coarsest first. We pick the largest intlen whose max
# position error stays under the zone threshold. The finest entries
# (0.01 d ≈ 14 min, 0.003 d ≈ 4 min) exist for high-velocity planetary
# flybys — Voyager 2 at Neptune periapsis (27 km/s @ 4,950 km) needs short
# segments because the deflection at periapsis is too sharp for a degree-11
# polynomial over a longer window.
INTLEN_SWEEP_DAYS: tuple[float, ...] = (
    30.0,
    10.0,
    3.0,
    1.0,
    0.3,
    0.1,
    0.03,
    0.01,
    0.003,
)
CHEBYSHEV_DEGREE = 11

# Method tags. Pure = snapshot Kepler (6 elements, no drift). Drift =
# snapshot + linearly-fit Ω̇/ω̇/Ṁ (9 elements). The export side uses
# different payload sizes per method.
METHOD_KEPLER_PURE = "kepler_pure"
METHOD_KEPLER_DRIFT = "kepler_drift"
METHOD_CHEBYSHEV = "chebyshev"
METHOD_UNCOVERABLE = "uncoverable"


def _chebyshev_bytes_per_segment(float64_coeffs: bool) -> int:
    """3 axes × (degree+1) coefficients per Chebyshev segment. Segment time
    bounds are *not* stored per-segment for probes — they're implicit from
    the sub-chunk start + uniform `intlen_s`."""
    coeff_bytes = 8 if float64_coeffs else 4
    return 3 * (CHEBYSHEV_DEGREE + 1) * coeff_bytes


def _kepler_bytes(method: str, float64_coeffs: bool) -> int:
    """Per-sub-chunk Kepler payload size.

    Pure = 6 elements (a, e, i, Ω₀, ω₀, M₀) + 1 anchor offset = 7 floats.
    Drift adds Ω̇/ω̇/Ṁ → 10 total.

    Anchor offset is `t_snap_et - sub_t_start_et` (seconds): the time the
    snapshot elements were taken at, relative to the sub-chunk's start.
    Without it the frontend can't tell where the snapshot anchor was, and
    `conics` propagates from the wrong epoch — which costs millions of km
    on heliocentric cruise probes.

    Mean motion `n` isn't stored: pure mode propagates M via mu in `conics`;
    drift mode bakes any J2 correction into the fitted Ṁ.
    """
    coeff_bytes = 8 if float64_coeffs else 4
    n_elements = 10 if method == METHOD_KEPLER_DRIFT else 7
    return n_elements * coeff_bytes


# Method-C fit samples per chunk for both the fit and the accuracy check.
SAMPLES_PER_CHUNK = 50
# How wide a window to draw Method-C samples from. Wider window captures
# long-period secular trends but assumes the orbit is well-approximated by
# linear drift over the window. ±0.5y is a reasonable middle ground for
# spacecraft (vs ±5y for natural moons whose perturbations are tiny).
METHOD_C_HALF_WINDOW_S = 0.5 * 365.25 * S_PER_DAY


@dataclass(frozen=True)
class SubChunkFit:
    """One sub-chunk's fit — either Method-C Kepler (snapshot + optional
    drift) or refit Chebyshev. Carries the actual numeric payload so the
    export writer can pack it directly; downstream callers wanting just
    byte counts read `.bytes`.
    """

    method: str  # METHOD_KEPLER_PURE | _DRIFT | _CHEBYSHEV | _UNCOVERABLE
    t_start_et: float
    t_end_et: float
    bytes: int
    max_err_km: float
    detail: str  # extra context (intlen for chebyshev, fit-residual for kepler)
    # Method-specific payload data (one set per method).
    kepler_elts: dict | None = None  # for kepler_pure / kepler_drift
    chebyshev_intlen_s: float | None = None  # uniform sub-segment length
    chebyshev_coeffs: np.ndarray | None = None  # (n_seg, 3, degree+1)


@dataclass(frozen=True)
class ChunkSizing:
    """Aggregate of all sub-chunks inside one streaming chunk."""

    total_bytes: int
    n_kepler: int
    n_chebyshev: int
    n_uncoverable: int
    max_err_km: float
    sub_chunks: list[SubChunkFit] = field(default_factory=list)


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
    # motion when polyfit is well-behaved (captures the J2 Ṁ correction),
    # else fall back to the analytic Kepler rate.
    #
    # Why the fallback: for short-period orbits (LEO, lunar orbiters) the
    # M-list wraps several times across the fit window. `np.unwrap`'s
    # default π threshold can miss wraps when sample spacing approaches
    # Nyquist, and the polyfit returns a meaningless slope (sometimes
    # negative). Without a drift variant, the caller is left with `pure`
    # only — which has no J2 Ω̇/ω̇ and accumulates km/h of along-track
    # error on Sun-sync orbits. Falling back to `n_kepler = sqrt(mu/a³)`
    # at least preserves the Keplerian rate; the polyfit-derived Ω̇/ω̇
    # still capture the dominant J2 nodal/apsidal precession.
    times_rel = valid_ts_arr - t_snap
    om_un = np.unwrap(np.asarray(om_list))
    w_un = np.unwrap(np.asarray(w_list))
    m_un = np.unwrap(np.asarray(m_list))
    om_dot, _ = np.polyfit(times_rel, om_un, 1)
    w_dot, _ = np.polyfit(times_rel, w_un, 1)
    n_mean_fit, _ = np.polyfit(times_rel, m_un, 1)
    a_snap = a_list[snap_idx]
    n_kepler = math.sqrt(mu / a_snap**3) if a_snap > 0 else 0.0
    if 0.5 * n_kepler < n_mean_fit < 1.5 * n_kepler:
        n_mean = float(n_mean_fit)
    elif n_kepler > 0:
        n_mean = float(n_kepler)
    else:
        return [pure]
    drift = {
        **base,
        "om_dot": float(om_dot),
        "w_dot": float(w_dot),
        "n_mean_rad_s": n_mean,
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


def _fit_chebyshev_subchunk(
    naif_id: int,
    fit_center_naif_id: int,
    t_start: float,
    t_end: float,
    intlen_s: float,
    n_eval_samples: int = 40,
) -> tuple[np.ndarray, float] | None:
    """Refit Chebyshev for one sub-chunk at `intlen_s` and return coefficients
    + max km residual against SPICE truth.

    Returns `(coeffs, max_err_km)` where `coeffs` has shape
    `(n_segments, 3, CHEBYSHEV_DEGREE + 1)`. Returns None on any SPICE
    sampling failure (caller treats as uncoverable). Implements the same
    polynomial fit as `download/providers/objects/chebyshev._sample_body`.

    All segments are fit (vs. the previous lazy-on-eval-point approach) so
    the resulting coefficient array can be packed into the export binary.

    TODO(discontinuity-aware fitting): old (1970s-era) SPKs have small
    step discontinuities at their internal intlen boundaries — e.g.
    p10-a.bsp at jd=2442040.5 has an 11 km position step. If a segment
    straddles such a step, the polynomial interpolates exactly at the 12
    Gauss-Lobatto nodes but oscillates ~step-size between them (Pioneer 10
    Jupiter shows a 9.7 km tip at one sample out of 1295). `n_eval_samples`
    is too coarse to detect this; finer intlen doesn't help because the
    step is at a fixed time. Real fix: sub-second-cadence scan to detect
    discontinuities, then choose an intlen + grid offset that aligns
    segment boundaries to the step location. See
    `scripts/probe_diagnose_pioneer10.py` for the worked-out case.
    """
    n_nodes = CHEBYSHEV_DEGREE + 1
    k = np.arange(n_nodes)
    nodes_tau = (
        np.cos(np.pi * k / CHEBYSHEV_DEGREE) if CHEBYSHEV_DEGREE > 0 else np.zeros(1)
    )

    # Uniformly divide the sub-chunk so segments are equal-width. The binary
    # format doesn't store per-segment bounds — frontend recovers them via
    # `seg_dt = sub_chunk_duration / n_segments`. If we kept variable-width
    # segments (last one clipped to `t_end`), the implicit reconstruction
    # would land on the wrong window and τ evaluates the wrong polynomial.
    n_segments = _chebyshev_sub_interval_count(intlen_s, t_end - t_start)
    seg_dt = (t_end - t_start) / n_segments
    seg_starts = t_start + np.arange(n_segments) * seg_dt
    seg_ends = seg_starts + seg_dt

    coeffs = np.zeros((n_segments, 3, n_nodes), dtype=np.float64)
    for seg_idx in range(n_segments):
        seg_start = seg_starts[seg_idx]
        seg_end = seg_ends[seg_idx]
        mid = 0.5 * (seg_start + seg_end)
        half = 0.5 * (seg_end - seg_start)
        sample_ets = mid + half * nodes_tau
        positions = np.empty((n_nodes, 3))
        for ii, samp_et in enumerate(sample_ets):
            s = _safe_spkezr(naif_id, float(samp_et), "ECLIPJ2000", fit_center_naif_id)
            if s is None:
                return None
            positions[ii] = s[0][:3]
        for axis in range(3):
            coeffs[seg_idx, axis] = np.polynomial.chebyshev.chebfit(
                nodes_tau, positions[:, axis], CHEBYSHEV_DEGREE
            )

    # Residual evaluation.
    eval_ets = np.linspace(t_start, t_end, n_eval_samples)
    max_err = 0.0
    for et in eval_ets:
        s = _safe_spkezr(naif_id, float(et), "ECLIPJ2000", fit_center_naif_id)
        if s is None:
            return None
        truth = s[0][:3]
        seg_idx = int(
            np.clip(np.searchsorted(seg_ends, et, side="left"), 0, n_segments - 1)
        )
        seg_start = seg_starts[seg_idx]
        seg_end = seg_ends[seg_idx]
        mid = 0.5 * (seg_start + seg_end)
        half = 0.5 * (seg_end - seg_start)
        tau = (et - mid) / half
        fitted = np.array(
            [
                np.polynomial.chebyshev.chebval(tau, coeffs[seg_idx, axis])
                for axis in range(3)
            ]
        )
        err = float(np.linalg.norm(fitted - truth))
        if err > max_err:
            max_err = err
    return coeffs, max_err


def _fit_sub_chunk(
    naif_id: int,
    zone: Zone,
    fit_center_naif_id: int,
    mu: float,
    sub_t_start: float,
    sub_t_end: float,
    base_threshold_km: float,
) -> SubChunkFit:
    """Pick Kepler vs Chebyshev for one sub-chunk and capture the fit data.

    Tries both Method-C variants (pure-Kepler-from-snapshot, drift-fitted)
    and keeps whichever has lower max-err on the sub-chunk. The Chebyshev
    sweep is reserved for cases where Kepler exceeds the (possibly relaxed)
    threshold.

    `base_threshold_km` is the zone default. If the probe's orbital period
    inferred from the fit is below the zone's short-orbit cutoff, the
    threshold is relaxed to `zone.short_orbit_threshold_km` (~500 km for
    planetary). Phase-shift visible at deep zoom but invisible at the
    typical planet-system view.
    """
    sub_s = sub_t_end - sub_t_start
    sub_mid = 0.5 * (sub_t_start + sub_t_end)
    cheb_bytes_per_seg = _chebyshev_bytes_per_segment(zone.float64_coeffs)

    # Fit window: default ±2 days. Narrow it for short-period orbits — for a
    # 2-hour lunar orbiter (Chandrayaan-2, Danuri, LRO, LADEE), a wide window
    # averages over 48 mascon-perturbed orbits and the linear-drift assumption
    # in Method-C collapses (~2500 km median error, samples dipping below the
    # lunar surface). Scaling the half-window to ~2 orbital periods preserves
    # statistical power for the Ω̇/ω̇/Ṁ fit while keeping the linear assumption
    # locally valid (~150 km median for the same probes, never below surface).
    default_half_s = max(2.0 * sub_s, 2 * S_PER_DAY)
    # Estimate the orbital period from multi-sample oscelt over a wide window.
    # A single oscelt at sub_mid is unreliable for high-e orbits — INTEGRAL's
    # instantaneous osculating period collapses to ~3 h near perigee even
    # though the real orbit is multi-day, because small lunar third-body
    # velocity perturbations push the osculating energy way off. Sampling
    # broadly (≥1 month for earth-moon) and taking the max period across
    # samples biases toward apogee-side samples where the osculating elements
    # are stable. For genuinely short-period orbits every sample agrees on
    # the period, so the max equals the actual.
    prelim_window_s = max(default_half_s, 15 * S_PER_DAY)
    prelim_ets = np.linspace(sub_mid - prelim_window_s, sub_mid + prelim_window_s, 21)
    max_period_s = 0.0
    for et in prelim_ets:
        state = _safe_spkezr(naif_id, float(et), "ECLIPJ2000", fit_center_naif_id)
        if state is None:
            continue
        try:
            rp_p, ecc_p, _, _, _, _, _, _ = spiceypy.oscelt(state[0], float(et), mu)
        except spiceypy.exceptions.SpiceyError:
            continue
        if not (0 < ecc_p < 1.0 and rp_p > 0):
            continue
        period_s = 2.0 * math.pi * math.sqrt((rp_p / (1 - ecc_p)) ** 3 / mu)
        max_period_s = max(max_period_s, period_s)
    # Fit window scales to ~2 orbital periods so the Method-C linear-drift
    # assumption stays locally valid. Short-period orbits (lunar orbiters,
    # WISE/LEO) get a narrow window — averaging over many mascon- or J2-
    # perturbed orbits collapses the fit, and a 6-hour-class window puts
    # M past the np.unwrap reliability edge (4+ wraps near Nyquist).
    # Long-period orbits (INTEGRAL, halo) get a wide default window so
    # the fit samples span a meaningful arc of the orbit rather than just
    # the near-perigee fast pass.
    if max_period_s > 0:
        fit_half_s = min(default_half_s, 2.0 * max_period_s)
    else:
        fit_half_s = default_half_s
    # 200 fit samples gives Nyquist-clean coverage at any reasonable window.
    fit_ets = np.linspace(sub_mid - fit_half_s, sub_mid + fit_half_s, 200)
    variants = _fit_method_c(naif_id, fit_center_naif_id, mu, fit_ets)

    kepler_err = float("inf")
    if variants:
        eval_ets = np.linspace(sub_t_start, sub_t_end, 20)
        best_v: tuple[dict, float] | None = None
        for v in variants:
            err = _kepler_max_err_km(v, naif_id, fit_center_naif_id, eval_ets)
            if best_v is None or err < best_v[1]:
                best_v = (v, err)
        if best_v is not None:
            kepler_err = best_v[1]
            # Use the prelim multi-sample max period for the short-period
            # decision rather than the fitted snapshot's a_km. For high-e
            # orbits the snapshot a near perigee collapses to nonsense (e.g.
            # INTEGRAL: snapshot a=17000 km, fitted period ~6 h, vs real
            # ~3-day period), and would incorrectly flag as short-period and
            # force Kepler. The prelim sweeps a wide window so apogee-side
            # samples reveal the true period.
            period_s = (
                max_period_s
                if max_period_s > 0
                else 2 * math.pi * math.sqrt(best_v[0]["a_km"] ** 3 / mu)
            )
            is_short_period = period_s < zone.short_orbit_period_s
            threshold_km = (
                max(base_threshold_km, zone.short_orbit_threshold_km)
                if is_short_period
                else base_threshold_km
            )
            # For short-period orbiters (sub-day periods around a planet/moon)
            # Chebyshev's degree-11 polynomial covers multiple orbital cycles
            # per segment at any byte budget we can afford. Pin to whichever
            # Kepler variant has lower residual rather than fall through to a
            # Chebyshev that will alias and put the probe below the body's
            # surface — accuracy_threshold is advisory in this regime.
            if kepler_err <= threshold_km or is_short_period:
                method = (
                    METHOD_KEPLER_DRIFT
                    if best_v[0].get("mode") == "drift"
                    else METHOD_KEPLER_PURE
                )
                detail = (
                    f"{best_v[0]['mode']} thresh={threshold_km:.0f}km"
                    if kepler_err <= threshold_km
                    else f"{best_v[0]['mode']} short-period-forced (err {kepler_err:.0f}km)"
                )
                return SubChunkFit(
                    method=method,
                    t_start_et=sub_t_start,
                    t_end_et=sub_t_end,
                    bytes=_kepler_bytes(method, zone.float64_coeffs),
                    max_err_km=kepler_err,
                    detail=detail,
                    kepler_elts=best_v[0],
                )
        else:
            threshold_km = base_threshold_km
    else:
        threshold_km = base_threshold_km

    # Chebyshev fallback. Try coarsest intlen first; keep the first whose
    # max residual is below threshold. Otherwise keep the lowest-error one.
    best_under: tuple[float, float, np.ndarray] | None = None
    best_over: tuple[float, float, np.ndarray] | None = None
    for intlen_d in INTLEN_SWEEP_DAYS:
        intlen_s = intlen_d * S_PER_DAY
        seg_s = min(intlen_s, sub_s)
        result = _fit_chebyshev_subchunk(
            naif_id, fit_center_naif_id, sub_t_start, sub_t_end, seg_s
        )
        if result is None:
            return SubChunkFit(
                method=METHOD_UNCOVERABLE,
                t_start_et=sub_t_start,
                t_end_et=sub_t_end,
                bytes=0,
                max_err_km=float("nan"),
                detail="spkezr failed mid-sub-chunk",
            )
        coeffs, err = result
        if err <= threshold_km:
            best_under = (intlen_d, err, coeffs)
            break
        if best_over is None or err < best_over[1]:
            best_over = (intlen_d, err, coeffs)

    chosen = best_under if best_under is not None else best_over
    if chosen is None:
        return SubChunkFit(
            method=METHOD_UNCOVERABLE,
            t_start_et=sub_t_start,
            t_end_et=sub_t_end,
            bytes=0,
            max_err_km=float("nan"),
            detail="no fits possible",
        )
    intlen_d, err, coeffs = chosen
    detail = (
        f"intlen={intlen_d}d kepler_err={kepler_err:.1g}km"
        if best_under is not None
        else f"intlen={intlen_d}d OVER_THRESH"
    )
    return SubChunkFit(
        method=METHOD_CHEBYSHEV,
        t_start_et=sub_t_start,
        t_end_et=sub_t_end,
        bytes=coeffs.shape[0] * cheb_bytes_per_seg,
        max_err_km=err,
        detail=detail,
        chebyshev_intlen_s=intlen_d * S_PER_DAY,
        chebyshev_coeffs=coeffs,
    )


def size_chunk(
    naif_id: int,
    zone: Zone,
    t_start: float,
    t_end: float,
    fit_center_naif_id: int | None = None,
) -> ChunkSizing:
    """Slice the streaming chunk into Kepler-width sub-chunks, fit each.

    Each sub-chunk decides independently between Method-C Kepler (cheap:
    9 floats = 36 bytes) and Chebyshev (refit-and-pack like
    `download/providers/objects/chebyshev.py`). The overall chunk's byte
    cost is the sum of its sub-chunks.

    `fit_center_naif_id` overrides the zone's default fit center for this
    chunk — e.g. a lunar orbiter in `earth-moon` gets fit around the Moon
    (301) instead of Earth (399). When None, falls back to
    `zone.fit_center_naif_id`. The caller decides whether the probe sits
    inside an alternate primary's Hill sphere; this function just trusts
    the choice and routes mu + spkezr accordingly.
    """
    center = (
        fit_center_naif_id
        if fit_center_naif_id is not None
        else zone.fit_center_naif_id
    )
    try:
        mu = spiceypy.bodvrd(str(center), "GM", 1)[1][0]
    except spiceypy.exceptions.SpiceyError:
        return ChunkSizing(0, 0, 0, 1, float("inf"), [])

    base_threshold_km = threshold_for(zone, naif_id)
    sub_s = zone.kepler_subchunk_days * S_PER_DAY

    sub_chunks: list[SubChunkFit] = []
    cur = t_start
    while cur < t_end:
        nxt = min(cur + sub_s, t_end)
        sub_chunks.append(
            _fit_sub_chunk(naif_id, zone, center, mu, cur, nxt, base_threshold_km)
        )
        cur = nxt

    n_kepler = sum(
        1 for s in sub_chunks if s.method in (METHOD_KEPLER_PURE, METHOD_KEPLER_DRIFT)
    )
    n_chebyshev = sum(1 for s in sub_chunks if s.method == METHOD_CHEBYSHEV)
    n_uncoverable = sum(1 for s in sub_chunks if s.method == METHOD_UNCOVERABLE)
    finite_errs = [s.max_err_km for s in sub_chunks if math.isfinite(s.max_err_km)]
    return ChunkSizing(
        total_bytes=sum(s.bytes for s in sub_chunks),
        n_kepler=n_kepler,
        n_chebyshev=n_chebyshev,
        n_uncoverable=n_uncoverable,
        max_err_km=max(finite_errs, default=0.0),
        sub_chunks=sub_chunks,
    )
