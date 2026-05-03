"""Compare propagation methods for non-Chebyshev moons against SPICE truth.

For every moon in loaded SPK kernels that is **not** in
`CHEBYSHEV_MOON_WHITELIST`, this script computes three trajectories:

  Method A — current shipping behaviour: single-epoch (osculating) Keplerian
             elements in ECLIPJ2000, propagated by linear mean-anomaly drift.
  Method B — single-epoch (osculating) elements in the parent's equatorial
             frame plus analytic J2 secular rates Ω̇/ω̇ (formulas in
             spice.py:33+). Rotated back to ECLIPJ2000 for comparison.
             Failed earlier validation: osculating snapshot bakes in a
             phase-drift bias that J2 rates cannot remove.
  Method C — fit mean elements numerically: sample SPK over ~100 orbital
             periods, average a/e/i, linear-fit Ω(t)/ω(t)/M(t) (unwrapped) for
             secular rates that automatically include J2/J4/etc. Fit residual
             RMS is reported as a per-body diagnostic — bodies with high
             residuals can't be modelled secularly and should fall back to
             Chebyshev.
  Truth   — `spkezr` evaluated at each test epoch.

For each moon and test horizon (Δt = 30 d, 1 y, 5 y, 20 y) the script reports
position error in km plus A/C and B/C improvement factors. The shipping bar
is ≥5× improvement on fast inner moons.

Run with the kernels already downloaded under `space-map-downloads/spice/kernels`.
"""

import math
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import spiceypy

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "data" / "src"))

from space_map_data.utils.naif import (  # noqa: E402
    CHEBYSHEV_MOON_WHITELIST,
    classify_object,
)
from space_map_data.models.object import ObjectType  # noqa: E402
from space_map_data.utils.paths import DOWNLOAD_DIR  # noqa: E402
from space_map_data.download.providers.objects.chebyshev import (  # noqa: E402
    _MOON_MIN_INTLEN_S,
    _native_params,
)

KERNEL_DIR = DOWNLOAD_DIR / "spice" / "kernels"
EPOCH_UTC = "2026-01-01T00:00:00"
HORIZONS_DAYS = (30.0, 365.25, 5 * 365.25, 20 * 365.25)
S_PER_DAY = 86400.0


# ---------------------------------------------------------------------------
# Frame conversion
# ---------------------------------------------------------------------------


def _pole_body_id(parent_naif_id: int) -> int:
    """Map a planetary barycenter ID (1..9) to the planet ID (199..999) that
    actually has POLE_RA in the PCK. Pass-through for other IDs (e.g. 301)."""
    if 1 <= parent_naif_id <= 9:
        return parent_naif_id * 100 + 99
    return parent_naif_id


def parent_equatorial_rot(parent_naif_id: int, et: float) -> np.ndarray:
    """3x3 rotation matrix ECLIPJ2000 → parent-equatorial-J2000-inertial.

    Pole RA/Dec are evaluated at `et` from the PCK rotation polynomial. The
    result is an *inertial* frame frozen at this epoch (no spin term applied).

    Frame definition: Z axis along the parent's pole (toward `+pole`), X axis
    in the ECLIPJ2000 equatorial plane (perpendicular to Z, no roll), Y from
    Z × X. The frame's X is the ascending node of the parent equator on the
    ecliptic.
    """
    pole_body = _pole_body_id(parent_naif_id)
    pole_ra = spiceypy.bodvrd(str(pole_body), "POLE_RA", 3)[1]
    pole_dec = spiceypy.bodvrd(str(pole_body), "POLE_DEC", 3)[1]
    T = et / (100 * 365.25 * S_PER_DAY)  # Julian centuries past J2000
    ra_deg = pole_ra[0] + pole_ra[1] * T
    dec_deg = pole_dec[0] + pole_dec[1] * T

    # SPICE pole RA/Dec are in ICRF (Earth-equatorial J2000). Build ICRF→pole
    # rotation, then prepend ECLIPJ2000→ICRF.
    ra = math.radians(ra_deg)
    dec = math.radians(dec_deg)
    z_icrf = np.array(
        [math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec)]
    )
    # Node on ICRF equator: cross(Z_icrf=(0,0,1), pole) — same as the standard
    # formula. SPICE convention for prime meridian uses Q = pole × ICRF_z, but
    # for the inertial frame here we just need any consistent X.
    icrf_z = np.array([0.0, 0.0, 1.0])
    x_axis = np.cross(icrf_z, z_icrf)
    if np.linalg.norm(x_axis) < 1e-12:
        x_axis = np.array([1.0, 0.0, 0.0])
    x_axis /= np.linalg.norm(x_axis)
    y_axis = np.cross(z_icrf, x_axis)
    rot_icrf_to_eq = np.stack([x_axis, y_axis, z_icrf])  # rows are new basis

    rot_ecl_to_icrf = spiceypy.pxform("ECLIPJ2000", "J2000", et)
    return rot_icrf_to_eq @ rot_ecl_to_icrf


# ---------------------------------------------------------------------------
# Element extraction & propagation
# ---------------------------------------------------------------------------


@dataclass
class Elements:
    a_km: float
    e: float
    i_rad: float
    om_rad: float
    w_rad: float
    m0_rad: float
    n_rad_s: float
    epoch_et: float
    om_dot_rad_s: float = 0.0
    w_dot_rad_s: float = 0.0


def state_to_elements(state: np.ndarray, et: float, mu: float) -> Elements | None:
    try:
        elts = spiceypy.oscelt(state, et, mu)
    except spiceypy.exceptions.SpiceyError:
        return None
    rp, ecc, inc, lnode, argp, m0, _t0, mu_out = elts
    if ecc >= 1.0 or rp <= 0:
        return None
    a = rp / (1 - ecc)
    if a <= 0:
        return None
    n = math.sqrt(mu_out / a**3)
    return Elements(a, ecc, inc, lnode, argp, m0, n, et)


def j2_rates(elts: Elements, j2: float, r_eq: float) -> tuple[float, float]:
    """Analytic secular Ω̇ and ω̇ in rad/s, given equatorial-frame elements."""
    a = elts.a_km
    e = elts.e
    n = elts.n_rad_s
    cos_i = math.cos(elts.i_rad)
    factor = n * j2 * (r_eq / a) ** 2 / (1 - e**2) ** 2
    om_dot = -1.5 * factor * cos_i
    w_dot = 0.75 * factor * (5 * cos_i**2 - 1)
    return om_dot, w_dot


def kepler_E(M: float, e: float) -> float:
    """Solve Kepler's equation by Newton iteration; M in [-pi, pi]."""
    M = ((M + math.pi) % (2 * math.pi)) - math.pi
    E = M if e < 0.8 else math.pi
    for _ in range(50):
        f = E - e * math.sin(E) - M
        fp = 1 - e * math.cos(E)
        dE = f / fp
        E -= dE
        if abs(dE) < 1e-12:
            break
    return E


def propagate_elements(elts: Elements, et: float) -> np.ndarray:
    """Propagate to absolute time `et`; return Cartesian position in same
    frame as the elements."""
    dt = et - elts.epoch_et
    M = elts.m0_rad + elts.n_rad_s * dt
    om = elts.om_rad + elts.om_dot_rad_s * dt
    w = elts.w_rad + elts.w_dot_rad_s * dt
    E = kepler_E(M, elts.e)
    cos_E, sin_E = math.cos(E), math.sin(E)
    a = elts.a_km
    e = elts.e
    x_orb = a * (cos_E - e)
    y_orb = a * math.sqrt(1 - e**2) * sin_E

    cos_om, sin_om = math.cos(om), math.sin(om)
    cos_w, sin_w = math.cos(w), math.sin(w)
    cos_i, sin_i = math.cos(elts.i_rad), math.sin(elts.i_rad)
    R = np.array(
        [
            [
                cos_om * cos_w - sin_om * sin_w * cos_i,
                -cos_om * sin_w - sin_om * cos_w * cos_i,
                sin_om * sin_i,
            ],
            [
                sin_om * cos_w + cos_om * sin_w * cos_i,
                -sin_om * sin_w + cos_om * cos_w * cos_i,
                -cos_om * sin_i,
            ],
            [sin_w * sin_i, cos_w * sin_i, cos_i],
        ]
    )
    return R @ np.array([x_orb, y_orb, 0.0])


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def furnish_all() -> list[Path]:
    paths = sorted(KERNEL_DIR.glob("*"))
    paths = [p for p in paths if p.suffix in (".bsp", ".tpc", ".tls")]
    for p in paths:
        spiceypy.furnsh(str(p))
    return paths


def enumerate_moons(kernel_paths: list[Path]) -> list[tuple[int, int, str]]:
    """Return (naif_id, parent_naif_id, name) for every moon in any SPK."""
    seen: dict[int, tuple[int, str]] = {}
    for p in kernel_paths:
        if p.suffix != ".bsp":
            continue
        for nid in spiceypy.spkobj(str(p)):
            naif_id = int(nid)
            if naif_id in seen:
                continue
            try:
                name = spiceypy.bodc2n(naif_id)
            except spiceypy.exceptions.SpiceyError:
                name = ""
            try:
                obj_type, parent = classify_object(naif_id, name, name, None)
            except ValueError:
                continue
            if obj_type != ObjectType.moon:
                continue
            seen[naif_id] = (parent, name)
    return [(nid, p, n) for nid, (p, n) in sorted(seen.items())]


def parent_j2_r_eq(parent_naif_id: int) -> tuple[float, float] | None:
    """Look up J2 and equatorial radius for a planet barycenter (1..9).

    Tries BODY{n}_J2 first (system-bary entry), then BODY{n*100+99}_J2 (planet
    itself). Equatorial radius from the planet's RADII.
    """
    j2 = None
    for nid in (parent_naif_id, parent_naif_id * 100 + 99):
        try:
            j2 = float(spiceypy.bodvrd(str(nid), "J2", 1)[1][0])
            break
        except spiceypy.exceptions.SpiceyError:
            continue
    if j2 is None:
        return None
    try:
        r_eq = float(spiceypy.bodvrd(str(parent_naif_id * 100 + 99), "RADII", 3)[1][0])
    except spiceypy.exceptions.SpiceyError:
        return None
    return j2, r_eq


def parent_mu(parent_naif_id: int) -> float | None:
    try:
        return float(spiceypy.bodvrd(str(parent_naif_id), "GM", 1)[1][0])
    except spiceypy.exceptions.SpiceyError:
        return None


def cheb_size_kb_per_year(naif_id: int, kernel_paths: list[Path]) -> float | None:
    """Estimate the Chebyshev export size for one moon, in KB per year.

    Mirrors the logic in `chebyshev.extract_chebyshev`: native sub-interval
    floored at `_MOON_MIN_INTLEN_S` (0.5 d) for moons, native polynomial
    degree, 3-axis float32 coefficients + two float64 timestamps per segment.
    Returns None when the body has no Type-2/3 SPK segment.
    """
    native = _native_params(kernel_paths, naif_id)
    if native is None:
        return None
    intlen_s, degree = native
    intlen_s = max(intlen_s, _MOON_MIN_INTLEN_S)
    intervals_per_year = 365.25 * S_PER_DAY / intlen_s
    bytes_per_interval = (degree + 1) * 3 * 4 + 2 * 8  # 3 axes x f32 coeffs + 2 f64 jds
    return intervals_per_year * bytes_per_interval / 1024.0


def fit_mean_elements(
    naif_id: int,
    parent_naif_id: int,
    et_center: float,
    mu: float,
    n_orbits: int = 100,
    n_samples: int = 200,
    max_span_s: float = 10 * 365.25 * S_PER_DAY,
) -> tuple[Elements, float] | None:
    """Sample SPK around `et_center` and fit secular Keplerian elements.

    Returns (elements, residual_rms_rad). Mean a/e/i are time averages over
    the window; (Ω, ω, M) come from a linear fit of the unwrapped angle vs
    time, giving (Ω₀, Ω̇), (ω₀, ω̇), (M₀, n_mean). The residual RMS is the
    combined per-sample RMS error of those three linear fits in radians —
    large values indicate the secular model is inadequate (chaotic orbit,
    high-i_eq plane precession aliasing into ecliptic frame, mean-motion
    resonance, …) and the body should be moved to Chebyshev.

    Window length is `min(n_orbits · T_est, max_span_s)`. n_orbits=100 catches
    short-period oscillations cleanly for periods up to a few days; the cap
    keeps very-long-period outer irregulars (T ~ years) from over-extending.
    """
    try:
        st0, _ = spiceypy.spkezr(
            str(naif_id), et_center, "ECLIPJ2000", "NONE", str(parent_naif_id)
        )
    except spiceypy.exceptions.SpiceyError:
        return None
    seed = state_to_elements(np.asarray(st0), et_center, mu)
    if seed is None:
        return None
    period_s = 2 * math.pi * math.sqrt(seed.a_km**3 / mu)
    span_s = min(n_orbits * period_s, max_span_s)

    times = np.linspace(et_center - span_s / 2, et_center + span_s / 2, n_samples)
    a_arr = np.empty(n_samples)
    e_arr = np.empty(n_samples)
    i_arr = np.empty(n_samples)
    om_arr = np.empty(n_samples)
    w_arr = np.empty(n_samples)
    M_arr = np.empty(n_samples)
    for k, t in enumerate(times):
        try:
            st, _ = spiceypy.spkezr(
                str(naif_id), float(t), "ECLIPJ2000", "NONE", str(parent_naif_id)
            )
        except spiceypy.exceptions.SpiceyError:
            return None
        try:
            elts = spiceypy.oscelt(np.asarray(st), float(t), mu)
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

    times_rel = times - et_center  # so polyfit intercept = value at et_center
    om_un = np.unwrap(om_arr)
    w_un = np.unwrap(w_arr)
    M_un = np.unwrap(M_arr)
    om_dot, om0 = np.polyfit(times_rel, om_un, 1)
    w_dot, w0 = np.polyfit(times_rel, w_un, 1)
    n_mean, M0 = np.polyfit(times_rel, M_un, 1)

    om_res = om_un - (om_dot * times_rel + om0)
    w_res = w_un - (w_dot * times_rel + w0)
    M_res = M_un - (n_mean * times_rel + M0)
    res_rms = math.sqrt(
        float(np.mean(om_res**2)) + float(np.mean(w_res**2)) + float(np.mean(M_res**2))
    )

    return (
        Elements(
            a_km=float(np.mean(a_arr)),
            e=float(np.mean(e_arr)),
            i_rad=float(np.mean(i_arr)),
            om_rad=float(om0),
            w_rad=float(w0),
            m0_rad=float(M0),
            n_rad_s=float(n_mean),
            epoch_et=et_center,
            om_dot_rad_s=float(om_dot),
            w_dot_rad_s=float(w_dot),
        ),
        res_rms,
    )


@dataclass
class Row:
    naif_id: int
    parent: int
    name: str
    a_over_r: float
    i_eq_deg: float
    period_d: float
    res_rms_rad: float
    err_a: list[float]
    err_b: list[float]
    err_c: list[float]
    cheb_kb_per_year: float | None


def _quantile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return float("nan")
    idx = max(0, min(len(sorted_vals) - 1, int(q * (len(sorted_vals) - 1))))
    return sorted_vals[idx]


def main() -> None:
    kernel_paths = furnish_all()
    print(f"Furnished {len(kernel_paths)} kernels from {KERNEL_DIR}")
    et0 = spiceypy.str2et(EPOCH_UTC)
    moons = enumerate_moons(kernel_paths)
    print(f"Found {len(moons)} moons in SPK kernels (whitelisted ones included)")

    horizons_label = ", ".join(f"{d:g}d" for d in HORIZONS_DAYS)
    print(f"Horizons: {horizons_label}\n")
    print(
        f"{'naif':>6} {'parent':>6} {'name':<14} {'a/R':>7} {'i_eq°':>6} "
        f"{'T_d':>7} {'res_′':>7} "
        + " ".join(f"{f'A_{d:g}d':>11}" for d in HORIZONS_DAYS)
        + " "
        + " ".join(f"{f'C_{d:g}d':>11}" for d in HORIZONS_DAYS)
        + " "
        + " ".join(f"{f'A/C_{d:g}d':>9}" for d in HORIZONS_DAYS)
    )

    rows: list[Row] = []
    skipped_no_j2: list[str] = []
    skipped_other: list[tuple[str, str]] = []
    skipped_fit: list[str] = []

    for naif_id, parent, name in moons:
        if name.lower() in CHEBYSHEV_MOON_WHITELIST:
            continue
        gravity = parent_j2_r_eq(parent)
        if gravity is None:
            skipped_no_j2.append(name or str(naif_id))
            continue
        j2, r_eq = gravity
        mu = parent_mu(parent)
        if mu is None:
            skipped_other.append((name or str(naif_id), "no parent mu"))
            continue

        try:
            state_ecl, _ = spiceypy.spkezr(
                str(naif_id), et0, "ECLIPJ2000", "NONE", str(parent)
            )
        except spiceypy.exceptions.SpiceyError as exc:
            skipped_other.append((name or str(naif_id), f"spkezr fail: {exc}"))
            continue

        rot = parent_equatorial_rot(parent, et0)
        rot6 = np.zeros((6, 6))
        rot6[:3, :3] = rot
        rot6[3:, 3:] = rot
        state_eq = rot6 @ np.asarray(state_ecl)

        elts_ecl = state_to_elements(np.asarray(state_ecl), et0, mu)
        elts_eq = state_to_elements(state_eq, et0, mu)
        if elts_ecl is None or elts_eq is None:
            skipped_other.append((name or str(naif_id), "degenerate elements"))
            continue

        # Method B: J2 rates from osculating snapshot in equatorial frame
        om_dot_b, w_dot_b = j2_rates(elts_eq, j2, r_eq)
        elts_eq.om_dot_rad_s = om_dot_b
        elts_eq.w_dot_rad_s = w_dot_b

        # Method C: numerical mean-element fit (in ecliptic, our prop frame)
        fit = fit_mean_elements(naif_id, parent, et0, mu)
        if fit is None:
            skipped_fit.append(name or str(naif_id))
            continue
        elts_c, res_rms = fit

        period_d = 2 * math.pi * math.sqrt(elts_c.a_km**3 / mu) / S_PER_DAY
        a_over_r = elts_c.a_km / r_eq
        i_eq_deg = math.degrees(elts_eq.i_rad)

        errs_a: list[float] = []
        errs_b: list[float] = []
        errs_c: list[float] = []
        for d in HORIZONS_DAYS:
            et_t = et0 + d * S_PER_DAY
            truth_state, _ = spiceypy.spkezr(
                str(naif_id), et_t, "ECLIPJ2000", "NONE", str(parent)
            )
            truth_ecl = np.asarray(truth_state[:3])
            pos_a = propagate_elements(elts_ecl, et_t)
            pos_b_ecl = rot.T @ propagate_elements(elts_eq, et_t)
            pos_c = propagate_elements(elts_c, et_t)
            errs_a.append(float(np.linalg.norm(pos_a - truth_ecl)))
            errs_b.append(float(np.linalg.norm(pos_b_ecl - truth_ecl)))
            errs_c.append(float(np.linalg.norm(pos_c - truth_ecl)))

        ratios_ac = [a / c if c > 0 else float("inf") for a, c in zip(errs_a, errs_c)]
        # res_rms in arcminutes for compactness in the table
        res_arcmin = math.degrees(res_rms) * 60
        print(
            f"{naif_id:>6} {parent:>6} {(name or '')[:14]:<14} "
            f"{a_over_r:>7.2f} {i_eq_deg:>6.1f} "
            f"{period_d:>7.3g} {res_arcmin:>7.2g} "
            + " ".join(f"{v:>11.3g}" for v in errs_a)
            + " "
            + " ".join(f"{v:>11.3g}" for v in errs_c)
            + " "
            + " ".join(f"{r:>9.2f}" for r in ratios_ac)
        )
        rows.append(
            Row(
                naif_id=naif_id,
                parent=parent,
                name=name,
                a_over_r=a_over_r,
                i_eq_deg=i_eq_deg,
                period_d=period_d,
                res_rms_rad=res_rms,
                err_a=errs_a,
                err_b=errs_b,
                err_c=errs_c,
                cheb_kb_per_year=cheb_size_kb_per_year(naif_id, kernel_paths),
            )
        )

    print(
        f"\nSkipped {len(skipped_no_j2)} moons (parent has no J2): "
        f"{', '.join(skipped_no_j2[:8])}{'...' if len(skipped_no_j2) > 8 else ''}"
    )
    if skipped_fit:
        print(
            f"Skipped {len(skipped_fit)} moons (fit failed): "
            f"{', '.join(skipped_fit[:8])}{'...' if len(skipped_fit) > 8 else ''}"
        )
    if skipped_other:
        print(
            f"Skipped {len(skipped_other)} moons (other): "
            f"{', '.join(name for name, _ in skipped_other[:8])}"
            f"{'...' if len(skipped_other) > 8 else ''}"
        )

    parent_names = {
        3: "Earth",
        4: "Mars",
        5: "Jupiter",
        6: "Saturn",
        7: "Uranus",
        8: "Neptune",
        9: "Pluto",
    }
    n_h = len(HORIZONS_DAYS)

    # Per-parent medians, A vs C only (B is known to ~match A)
    print("\nPer-parent medians (A = osculating Kepler, C = mean-element fit):")
    print(
        f"{'parent':<10} {'count':>5} "
        + " ".join(f"{f'medA_{d:g}d':>12}" for d in HORIZONS_DAYS)
        + " "
        + " ".join(f"{f'medC_{d:g}d':>12}" for d in HORIZONS_DAYS)
        + " "
        + " ".join(f"{f'medA/C_{d:g}d':>13}" for d in HORIZONS_DAYS)
    )
    by_parent: dict[int, list[Row]] = {}
    for r in rows:
        by_parent.setdefault(r.parent, []).append(r)
    for parent, group in sorted(by_parent.items()):
        meds_a = [statistics.median(r.err_a[j] for r in group) for j in range(n_h)]
        meds_c = [statistics.median(r.err_c[j] for r in group) for j in range(n_h)]
        meds_r = [
            statistics.median(
                (r.err_a[j] / r.err_c[j]) if r.err_c[j] > 0 else float("inf")
                for r in group
            )
            for j in range(n_h)
        ]
        label = parent_names.get(parent, str(parent))
        print(
            f"{label:<10} {len(group):>5} "
            + " ".join(f"{v:>12.3g}" for v in meds_a)
            + " "
            + " ".join(f"{v:>12.3g}" for v in meds_c)
            + " "
            + " ".join(f"{r:>13.2f}" for r in meds_r)
        )

    # A/C ratio at 5y horizon, by a/R band
    h5_idx = HORIZONS_DAYS.index(5 * 365.25)
    bands = [(0, 5), (5, 15), (15, 50), (50, float("inf"))]
    print("\nA/C ratio at 5y horizon, by a/R_parent band:")
    print(
        f"{'a/R band':<14} {'count':>5} {'p10':>8} {'p25':>8} {'p50':>8} {'p75':>8} {'p90':>8}"
    )
    for lo, hi in bands:
        ratios = sorted(
            (r.err_a[h5_idx] / r.err_c[h5_idx]) if r.err_c[h5_idx] > 0 else float("inf")
            for r in rows
            if lo <= r.a_over_r < hi
        )
        if not ratios:
            continue
        label = f"[{lo}, {hi if hi != float('inf') else '∞'})"
        print(
            f"{label:<14} {len(ratios):>5} "
            f"{_quantile(ratios, 0.10):>8.2f} {_quantile(ratios, 0.25):>8.2f} "
            f"{_quantile(ratios, 0.50):>8.2f} {_quantile(ratios, 0.75):>8.2f} "
            f"{_quantile(ratios, 0.90):>8.2f}"
        )

    # B/C at 5y to confirm B contributes nothing
    print("\nB/C ratio at 5y horizon, by a/R_parent band (B should also lose to C):")
    print(f"{'a/R band':<14} {'count':>5} {'p25':>8} {'p50':>8} {'p75':>8}")
    for lo, hi in bands:
        ratios = sorted(
            (r.err_b[h5_idx] / r.err_c[h5_idx]) if r.err_c[h5_idx] > 0 else float("inf")
            for r in rows
            if lo <= r.a_over_r < hi
        )
        if not ratios:
            continue
        label = f"[{lo}, {hi if hi != float('inf') else '∞'})"
        print(
            f"{label:<14} {len(ratios):>5} "
            f"{_quantile(ratios, 0.25):>8.2f} {_quantile(ratios, 0.50):>8.2f} "
            f"{_quantile(ratios, 0.75):>8.2f}"
        )

    # Method-C-inadequate bodies: linear secular model can't describe these
    # at all (close-in chaotic dynamics, librations, mean-motion resonances).
    # Diagnosed by the fit-residual RMS — separates cleanly from outer
    # irregulars where Method C wins despite finite residual. Threshold at
    # 4000′ (~67° of unwrapped angle drift over the fit window) is
    # well-separated from both populations in our data.
    #
    # For each, also report the err_C/err_A ratio so we can see whether C
    # gave any improvement at all, and the Chebyshev export cost so we can
    # weigh which expensive ones are worth flipping anyway.
    res_threshold_arcmin = 4000.0
    inadequate = [
        r for r in rows if math.degrees(r.res_rms_rad) * 60 > res_threshold_arcmin
    ]
    print(
        f"\nMethod C inadequate (fit residual > {res_threshold_arcmin:.0f}′): "
        f"{len(inadequate)} bodies. These need Chebyshev to be accurate."
    )
    print(
        f"{'naif':>6} {'p':>3} {'name':<14} {'a/R':>6} {'i_eq°':>6} {'T_d':>7} "
        f"{'res_′':>8} {'errA_5y':>10} {'errC_5y':>10} {'C/A':>5} "
        f"{'cheb_KB/y':>10}"
    )
    cheap, expensive, no_cheb = [], [], []
    for r in inadequate:
        if r.cheb_kb_per_year is None:
            no_cheb.append(r)
        elif r.cheb_kb_per_year < 60:
            cheap.append(r)
        else:
            expensive.append(r)
    for label, group in (
        ("CHEAP TO ADD (<60 KB/y)", cheap),
        ("EXPENSIVE (≥60 KB/y)", expensive),
        ("NO SPK COVERAGE", no_cheb),
    ):
        if not group:
            continue
        print(f"-- {label}: {len(group)} body(ies)")
        for r in sorted(group, key=lambda r: r.cheb_kb_per_year or 0):
            cheb_s = (
                f"{r.cheb_kb_per_year:>10.1f}"
                if r.cheb_kb_per_year is not None
                else f"{'-':>10}"
            )
            ratio = r.err_c[h5_idx] / r.err_a[h5_idx] if r.err_a[h5_idx] > 0 else 0
            print(
                f"{r.naif_id:>6} {r.parent:>3} {(r.name or '')[:14]:<14} "
                f"{r.a_over_r:>6.2f} {r.i_eq_deg:>6.1f} {r.period_d:>7.3g} "
                f"{math.degrees(r.res_rms_rad) * 60:>8.3g} "
                f"{r.err_a[h5_idx]:>10.3g} {r.err_c[h5_idx]:>10.3g} {ratio:>5.2f} "
                f"{cheb_s}"
            )
    if cheap:
        total_cheap = sum(r.cheb_kb_per_year or 0 for r in cheap)
        print(
            f"\nTotal Chebyshev budget if we add the CHEAP ones: "
            f"~{total_cheap:.1f} KB/year, ~{total_cheap * 100 / 1024:.1f} MB "
            f"for 100-year coverage."
        )
    if expensive:
        total_exp = sum(r.cheb_kb_per_year or 0 for r in expensive)
        print(
            f"Total Chebyshev budget if we add the EXPENSIVE ones: "
            f"~{total_exp:.1f} KB/year, ~{total_exp * 100 / 1024:.1f} MB "
            f"for 100-year coverage."
        )

    # Reference: cost of bodies already in the Chebyshev whitelist
    print("\nReference: Chebyshev cost of already-whitelisted moons:")
    print(f"{'naif':>6} {'p':>3} {'name':<14} {'cheb_KB/y':>10}")
    whitelist_costs: list[tuple[int, int, str, float]] = []
    for naif_id, parent, name in moons:
        if name.lower() not in CHEBYSHEV_MOON_WHITELIST:
            continue
        cost = cheb_size_kb_per_year(naif_id, kernel_paths)
        if cost is not None:
            whitelist_costs.append((naif_id, parent, name, cost))
    for naif_id, parent, name, cost in sorted(whitelist_costs, key=lambda x: x[3]):
        print(f"{naif_id:>6} {parent:>3} {(name or '')[:14]:<14} {cost:>10.1f}")
    if whitelist_costs:
        total_wl = sum(c for *_, c in whitelist_costs)
        print(f"  → {len(whitelist_costs)} bodies, ~{total_wl:.1f} KB/year total")

    spiceypy.kclear()


if __name__ == "__main__":
    main()
