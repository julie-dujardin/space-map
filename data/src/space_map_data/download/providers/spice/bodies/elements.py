"""Orbital element math and secular Keplerian fits over SPK coverage.

Non-whitelisted moons get a fitted secular Keplerian model rather than an
osculating snapshot — see `fit_moon_mean_elements`. Sampling SPK over ~100
orbital periods and linear-fitting Ω(t)/ω(t)/M(t) (unwrapped) captures J2/J4
nodal regression and apsidal precession without needing analytic Brouwer
formulas: 3-13x more accurate than the snapshot-Kepler baseline for outer
irregulars. Close-in chaotic shepherds (Pan, Atlas, Mab, …), where the linear
model fails, are flagged via fit-residual warnings — those need Chebyshev.
"""

import logging
import math
import tomllib

import numpy as np
import spiceypy

from space_map_data.utils.paths import CONFIG_FILE
from space_map_data.utils.time import S_PER_DAY, jd_to_et

logger = logging.getLogger(__name__)

# AU in km
AU_KM = 149_597_870.7

_CHEBYSHEV_DEFAULTS: dict[str, int | float] = {
    "start_year": 1600,
    "end_year": 2600,
    "chunk_years": 5,  # major / major_asteroids zones; moon zones use the
    # per-parent cadences in `CHEBYSHEV_PARENT_CHUNK_YEARS`
}

# Soft threshold for "linear secular model fits this orbit". RMS angle
# residual in arcminutes from the per-moon fit; exceeding it means the body
# would benefit from Chebyshev coverage. The 4000′ value cleanly separates
# the outer-irregular population (typically <2000′) from close-in chaotic
# shepherds (>4000′, often tens of thousands) in our validation.
METHOD_C_RESIDUAL_WARN_ARCMIN = 4000.0

_METHOD_C_N_ORBITS = 100
_METHOD_C_N_SAMPLES = 200
_METHOD_C_MAX_SPAN_S = 10 * 365.25 * 86400.0
# Nyquist puts the alias floor at 2 samples/period; in practice `np.unwrap`
# needs ~3-4 to reliably recover the true angle progression. Below this we
# refuse to fit and let the caller ship plain osculating elements.
_METHOD_C_MIN_SAMPLES_PER_PERIOD = 4.0

# Time-chunked Method C config — non-whitelisted moons get one fit per
# 6-month window centered on the chunk midpoint, so secular elements track
# Kozai-Lidov-style multi-decade drift instead of being a single linear
# approximation across the whole coverage range.
MOON_CHUNK_YEARS = 0.5
_MOON_CHUNK_FIT_HALF_WINDOW_S = 5 * 365.25 * 86400.0  # ±5 years of samples per fit
# Density of pre-samples for chunked fits. Coarser than the single-epoch fit
# (5 samples/period instead of 2/period) because we slice many windows out of
# one sample sequence, and outer irregulars have multi-hundred-day periods.
# Bounded per year so a long coverage window samples as densely as a short one.
_MOON_CHUNK_SAMPLES_PER_PERIOD = 5
_MOON_CHUNK_MIN_SAMPLES_PER_YEAR = 2.0
_MOON_CHUNK_MAX_SAMPLES_PER_YEAR = 36.0
# Fewest samples a chunk's linear fit is run on.
_MOON_CHUNK_MIN_FIT_SAMPLES = 5
# How far a chunk's validity span may poke past coverage: rounding only, since
# chunk edges and kernel edges both land on year boundaries.
_MOON_CHUNK_EDGE_TOLERANCE_S = 1.0


def load_chebyshev_config() -> dict[str, int | float]:
    """Read [chebyshev] settings from config.toml, falling back to defaults."""
    if not CONFIG_FILE.exists():
        return dict(_CHEBYSHEV_DEFAULTS)
    with CONFIG_FILE.open("rb") as f:
        config = tomllib.load(f)
    section = config.get("chebyshev", {})
    return {
        # year bounds are integers; chunk lengths may be fractional
        k: (
            int(section.get(k, v))
            if k in ("start_year", "end_year")
            else float(section.get(k, v))
        )
        for k, v in _CHEBYSHEV_DEFAULTS.items()
    }


def state_to_elements(
    state: list[float], et: float, gm: float
) -> dict[str, float] | None:
    """Convert a SPICE state vector to Keplerian elements in AU/deg/day units.

    Returns None if the orbit is degenerate (e.g. a barycenter at its own center).
    """
    try:
        elts = spiceypy.oscelt(state, et, gm)
    except spiceypy.exceptions.SpiceyError:
        return None

    rp = elts[0]  # periapsis distance [km]
    ecc = elts[1]  # eccentricity
    inc = elts[2]  # inclination [rad]
    lnode = elts[3]  # longitude of ascending node [rad]
    argp = elts[4]  # argument of periapsis [rad]
    m0 = elts[5]  # mean anomaly at epoch [rad]
    # elts[6] = epoch of periapsis [s past J2000]
    mu = elts[7]  # GM [km^3/s^2]

    if ecc >= 1.0 or rp <= 0:
        # Hyperbolic/parabolic or degenerate — shouldn't happen for bound orbits
        return None

    a_km = rp / (1 - ecc)
    if a_km <= 0:
        return None

    a_au = a_km / AU_KM

    # Mean motion: n = sqrt(mu / a^3) in rad/s -> deg/day
    n_rad_s = math.sqrt(mu / (a_km**3))
    n_deg_day = math.degrees(n_rad_s) * 86400

    return {
        "A": a_au,
        "EC": ecc,
        "IN": math.degrees(inc),
        "OM": math.degrees(lnode),
        "W": math.degrees(argp),
        "MA": math.degrees(m0),
        "N": n_deg_day,
    }


def dominant_partner_mu(gm_self: float, candidate_naifs: list[int]) -> float | None:
    """Effective mu for the heavier member of a two-body pair around their barycenter.

    When a massive body (planet, Sun) orbits its own system barycenter, its
    motion is driven not by GM of the barycenter but by the gravity of the
    next-heaviest member. The two-body reduction yields
      mu_eff = GM_partner^3 / (GM_self + GM_partner)^2
    which produces the correct Kepler ellipse matching the partner's period.
    Returns None if no candidate has a known GM.
    """
    best_gm = 0.0
    for naif in candidate_naifs:
        try:
            gm = spiceypy.bodvrd(str(naif), "GM", 1)[1][0]
        except spiceypy.exceptions.SpiceyError:
            continue
        best_gm = max(best_gm, gm)
    if best_gm <= 0:
        return None
    return best_gm**3 / (gm_self + best_gm) ** 2


def fit_moon_mean_elements(
    naif_id: int, parent_id: int, et: float, gm: float
) -> tuple[dict[str, float], float] | None:
    """Sample SPICE over ~100 orbital periods and fit secular Keplerian elements.

    Returns (elements_dict, residual_rms_rad); the dict adds `OM_DOT`/`W_DOT`
    (deg/day) to `state_to_elements`'s keys, from linear fits of each
    unwrapped angle against time — picking up J2/J4 secular drift without
    analytic formulas. The residual RMS flags orbits linear drift can't
    describe (those should be on Chebyshev).

    Returns None when the fit can't be performed (degenerate orbit, hyperbolic
    encounter, missing SPK coverage); caller falls back to a snapshot.
    """
    period_seed = state_to_elements(
        list(
            spiceypy.spkezr(str(naif_id), et, "ECLIPJ2000", "NONE", str(parent_id))[0]
        ),
        et,
        gm,
    )
    if period_seed is None:
        return None
    a_km_seed = period_seed["A"] * AU_KM
    period_s = 2 * math.pi * math.sqrt(a_km_seed**3 / gm)
    span_s = min(_METHOD_C_N_ORBITS * period_s, _METHOD_C_MAX_SPAN_S)

    # Refuse to fit when the SPK sampling cadence is coarser than
    # `_METHOD_C_MIN_SAMPLES_PER_PERIOD`. Below that, `np.unwrap` aliases full
    # orbits down to small angle steps and the linear fit on M produces a
    # near-zero (sometimes wrong-sign) "secular" mean motion. Caller falls
    # through to a plain osculating snapshot with no drift, which is at least
    # rotationally correct over short horizons. The bodies that hit this are
    # always close-in shepherds with sub-day periods and belong on the
    # Chebyshev whitelist anyway.
    samples_per_period = _METHOD_C_N_SAMPLES * period_s / span_s
    if samples_per_period < _METHOD_C_MIN_SAMPLES_PER_PERIOD:
        logger.warning(
            "naif %d: %.2f samples/period below alias threshold %.0f "
            "(period=%.3f d) — Method C disabled, falling back to osculating "
            "snapshot. Add to CHEBYSHEV_MOON_WHITELIST for accurate tracking.",
            naif_id,
            samples_per_period,
            _METHOD_C_MIN_SAMPLES_PER_PERIOD,
            period_s / 86400.0,
        )
        return None

    times = np.linspace(et - span_s / 2, et + span_s / 2, _METHOD_C_N_SAMPLES)
    a_arr = np.empty(_METHOD_C_N_SAMPLES)
    e_arr = np.empty(_METHOD_C_N_SAMPLES)
    i_arr = np.empty(_METHOD_C_N_SAMPLES)
    om_arr = np.empty(_METHOD_C_N_SAMPLES)
    w_arr = np.empty(_METHOD_C_N_SAMPLES)
    M_arr = np.empty(_METHOD_C_N_SAMPLES)
    for k, t in enumerate(times):
        try:
            st, _ = spiceypy.spkezr(
                str(naif_id), float(t), "ECLIPJ2000", "NONE", str(parent_id)
            )
            elts = spiceypy.oscelt(np.asarray(st), float(t), gm)
        except spiceypy.exceptions.SpiceyError:
            return None
        rp, ecc, inc, lnode, argp, m0, _t0, _mu = elts
        if ecc >= 1.0 or rp <= 0:
            return None
        a_arr[k] = rp / (1 - ecc)
        e_arr[k] = ecc
        i_arr[k] = inc
        om_arr[k] = lnode
        w_arr[k] = argp
        M_arr[k] = m0

    times_rel = times - et  # linear-fit intercept = value at et (epoch)
    om_un = np.unwrap(om_arr)
    w_un = np.unwrap(w_arr)
    M_un = np.unwrap(M_arr)
    om_dot_rad_s, om0 = np.polyfit(times_rel, om_un, 1)
    w_dot_rad_s, w0 = np.polyfit(times_rel, w_un, 1)
    n_rad_s, M0 = np.polyfit(times_rel, M_un, 1)

    om_res = om_un - (om_dot_rad_s * times_rel + om0)
    w_res = w_un - (w_dot_rad_s * times_rel + w0)
    M_res = M_un - (n_rad_s * times_rel + M0)
    res_rms = math.sqrt(
        float(np.mean(om_res**2)) + float(np.mean(w_res**2)) + float(np.mean(M_res**2))
    )

    a_mean_km = float(np.mean(a_arr))
    if a_mean_km <= 0 or n_rad_s <= 0:
        return None

    deg_per_day_per_rad_per_s = math.degrees(1.0) * 86400
    return (
        {
            "A": a_mean_km / AU_KM,
            "EC": float(np.mean(e_arr)),
            "IN": math.degrees(float(np.mean(i_arr))),
            "OM": math.degrees(float(om0)),
            "W": math.degrees(float(w0)),
            "MA": math.degrees(float(M0)),
            "N": float(n_rad_s) * deg_per_day_per_rad_per_s,
            "OM_DOT": float(om_dot_rad_s) * deg_per_day_per_rad_per_s,
            "W_DOT": float(w_dot_rad_s) * deg_per_day_per_rad_per_s,
        },
        res_rms,
    )


def _sample_elements(
    naif_id: int, parent_id: int, mu: float, times: np.ndarray
) -> np.ndarray | None:
    """`(6, n)` osculating `[a_km, e, i, om, w, M]` at `times`, angles in
    radians and unwrapped. None on an unbound or unsampleable state."""
    out = np.empty((6, times.size))
    for k, t in enumerate(times):
        try:
            st, _ = spiceypy.spkezr(
                str(naif_id), float(t), "ECLIPJ2000", "NONE", str(parent_id)
            )
            elts = spiceypy.oscelt(np.asarray(st), float(t), mu)
        except spiceypy.exceptions.SpiceyError:
            return None
        rp, ecc, inc, lnode, argp, m0, _t0, _mu = elts
        if ecc >= 1.0 or rp <= 0:
            return None
        out[:, k] = (rp / (1 - ecc), ecc, inc, lnode, argp, m0)
    for row in (3, 4, 5):
        out[row] = np.unwrap(out[row])
    return out


def _chunks_in_coverage(
    midpoints_et: np.ndarray,
    chunk_half_width_s: float,
    coverage_et: list[tuple[float, float]],
) -> list[tuple[float, float, np.ndarray]]:
    """`(lo, hi, selected)` per coverage window holding at least one chunk's
    whole validity span; `selected` masks those chunks."""
    in_window = []
    for lo, hi in coverage_et:
        selected = (
            midpoints_et - chunk_half_width_s >= lo - _MOON_CHUNK_EDGE_TOLERANCE_S
        ) & (midpoints_et + chunk_half_width_s <= hi + _MOON_CHUNK_EDGE_TOLERANCE_S)
        if selected.any():
            in_window.append((lo, hi, selected))
    return in_window


def fit_moon_chunked_elements(
    naif_id: int,
    parent_id: int,
    mu: float,
    chunk_midpoints_jd: list[float],
    chunk_half_width_s: float,
    coverage_et: list[tuple[float, float]],
) -> tuple[np.ndarray, np.ndarray] | None:
    """Compute Method C secular elements for each chunk midpoint.

    A chunk gets elements only when its validity span (midpoint ±
    `chunk_half_width_s`) lies inside one window of `coverage_et`, the moon's
    merged SPK coverage; its fit samples are the ±5-year neighbourhood cut to
    that window, so chunks near a coverage edge fit on a shorter span instead
    of reaching past it. Each window is pre-sampled once at high density and
    sliced per chunk — ~1000 spkezr calls per body instead of ~200 per chunk.

    Returns (chunk_midpoints_jd, elements_array), shape (n_chunks, 9):
    [a_au, e, i_deg, om_deg, w_deg, ma_deg, n_deg_day, om_dot_deg_day,
    w_dot_deg_day], NaN rows for chunks left without elements. None when no
    chunk gets elements, or a pre-sample fails (degenerate orbit).
    """
    midpoints_et = np.array([jd_to_et(jd) for jd in chunk_midpoints_jd])
    in_window = _chunks_in_coverage(midpoints_et, chunk_half_width_s, coverage_et)
    if not in_window:
        return None

    # Orbital period from a state inside the first useful window.
    probe_et = float(midpoints_et[in_window[0][2]][0])
    try:
        probe_state, _ = spiceypy.spkezr(
            str(naif_id), probe_et, "ECLIPJ2000", "NONE", str(parent_id)
        )
    except spiceypy.exceptions.SpiceyError:
        return None
    probe = state_to_elements(list(probe_state), probe_et, mu)
    if probe is None:
        return None
    period_s = 2 * math.pi * math.sqrt((probe["A"] * AU_KM) ** 3 / mu)
    year_s = 365.25 * S_PER_DAY
    samples_per_year = min(
        _MOON_CHUNK_MAX_SAMPLES_PER_YEAR,
        max(
            _MOON_CHUNK_MIN_SAMPLES_PER_YEAR,
            year_s / period_s * _MOON_CHUNK_SAMPLES_PER_PERIOD,
        ),
    )
    # Same alias guard as `fit_moon_mean_elements`: the per-year cap leaves very
    # fast moons below Nyquist, so they ship no chunked sidecar and stay on
    # their single-epoch fallback.
    samples_per_period = samples_per_year * period_s / year_s
    if samples_per_period < _METHOD_C_MIN_SAMPLES_PER_PERIOD:
        logger.warning(
            "naif %d: chunked fit %.2f samples/period below alias threshold "
            "%.0f (period=%.3f d) — skipping. Add to CHEBYSHEV_MOON_WHITELIST.",
            naif_id,
            samples_per_period,
            _METHOD_C_MIN_SAMPLES_PER_PERIOD,
            period_s / 86400.0,
        )
        return None

    deg_per_day_per_rad_per_s = math.degrees(1.0) * S_PER_DAY
    out = np.full((midpoints_et.size, 9), np.nan, dtype=np.float64)
    for lo, hi, selected in in_window:
        # Only the neighbourhood the selected chunks fit on is sampled.
        chosen = midpoints_et[selected]
        s_lo = max(lo, float(chosen[0]) - _MOON_CHUNK_FIT_HALF_WINDOW_S)
        s_hi = min(hi, float(chosen[-1]) + _MOON_CHUNK_FIT_HALF_WINDOW_S)
        n_samples = max(
            _MOON_CHUNK_MIN_FIT_SAMPLES, int((s_hi - s_lo) / year_s * samples_per_year)
        )
        times = np.linspace(s_lo, s_hi, n_samples)
        sampled = _sample_elements(naif_id, parent_id, mu, times)
        if sampled is None:
            return None
        a_arr, e_arr, i_arr, om_un, w_un, M_un = sampled
        for idx in np.flatnonzero(selected):
            midpoint_et = midpoints_et[idx]
            mask = (times >= midpoint_et - _MOON_CHUNK_FIT_HALF_WINDOW_S) & (
                times <= midpoint_et + _MOON_CHUNK_FIT_HALF_WINDOW_S
            )
            if mask.sum() < _MOON_CHUNK_MIN_FIT_SAMPLES:
                continue
            t_rel = times[mask] - midpoint_et
            om_dot, om0 = np.polyfit(t_rel, om_un[mask], 1)
            w_dot, w0 = np.polyfit(t_rel, w_un[mask], 1)
            n_rad_s, M0 = np.polyfit(t_rel, M_un[mask], 1)
            a_mean_km = float(np.mean(a_arr[mask]))
            if a_mean_km <= 0 or n_rad_s <= 0:
                continue
            out[idx] = (
                a_mean_km / AU_KM,
                float(np.mean(e_arr[mask])),
                math.degrees(float(np.mean(i_arr[mask]))),
                math.degrees(float(om0)),
                math.degrees(float(w0)),
                math.degrees(float(M0)),
                float(n_rad_s) * deg_per_day_per_rad_per_s,
                float(om_dot) * deg_per_day_per_rad_per_s,
                float(w_dot) * deg_per_day_per_rad_per_s,
            )

    if np.isnan(out[:, 0]).all():
        return None
    return np.asarray(chunk_midpoints_jd, dtype=np.float64), out


def fill_osculating_chunks(
    elements: np.ndarray,
    naif_id: int,
    parent_id: int,
    mu: float,
    chunk_midpoints_jd: list[float],
    chunk_half_width_s: float,
    coverage_et: list[tuple[float, float]],
) -> np.ndarray:
    """`elements` with each NaN row of a chunk inside coverage set to the
    osculating elements at its midpoint, without drift.

    For chunks Method C leaves empty — moons too fast for its sampling, or
    whose osculating orbit turns unbound inside the fit window. One element
    set per chunk keeps such a moon to its kernel's years and resets its
    drift every chunk. A chunk whose midpoint state is unbound stays NaN.
    Same `(n_chunks, 9)` layout as `fit_moon_chunked_elements`.
    """
    out = elements.copy()
    midpoints_et = np.array([jd_to_et(jd) for jd in chunk_midpoints_jd])
    for _lo, _hi, selected in _chunks_in_coverage(
        midpoints_et, chunk_half_width_s, coverage_et
    ):
        for idx in np.flatnonzero(selected & np.isnan(out[:, 0])):
            et = float(midpoints_et[idx])
            try:
                state, _ = spiceypy.spkezr(
                    str(naif_id), et, "ECLIPJ2000", "NONE", str(parent_id)
                )
            except spiceypy.exceptions.SpiceyError:
                continue
            elts = state_to_elements(list(state), et, mu)
            if elts is None:
                continue
            out[idx] = (
                elts["A"],
                elts["EC"],
                elts["IN"],
                elts["OM"],
                elts["W"],
                elts["MA"],
                elts["N"],
                0.0,
                0.0,
            )
    return out
