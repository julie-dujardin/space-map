"""Compare propagation methods for non-Chebyshev moons against SPICE truth.

For every moon in loaded SPK kernels that is **not** in
`CHEBYSHEV_MOON_WHITELIST`, this script computes three trajectories:

  Method A — current shipping behaviour: single-epoch Keplerian elements in
             ECLIPJ2000, propagated by linear mean-anomaly drift.
  Method B — proposed: single-epoch Keplerian elements in the parent's
             equatorial frame at epoch, plus analytic J2 secular rates Ω̇ and
             ω̇ (formulas in spice.py:33+). Propagated then rotated back to
             ECLIPJ2000 for comparison with truth.
  Truth   — `spkezr` evaluated at each test epoch.

For each moon and test horizon (Δt = 30 d, 1 y, 5 y, 20 y) the script reports
the position error of A and B in km, plus B-vs-A improvement factor. The
threshold for shipping is ≥5× improvement on fast inner moons; outer moons
that fail this bar should fall back to Method A (or the same elements without
rates), driven by `a / R_parent`.

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


def main() -> None:
    kernel_paths = furnish_all()
    print(f"Furnished {len(kernel_paths)} kernels from {KERNEL_DIR}")
    et0 = spiceypy.str2et(EPOCH_UTC)
    moons = enumerate_moons(kernel_paths)
    print(f"Found {len(moons)} moons in SPK kernels (whitelisted ones included)")

    # Header: per-horizon error (km) for A and B, ratio A/B
    horizons_label = ", ".join(f"{d:g}d" for d in HORIZONS_DAYS)
    print(f"Horizons: {horizons_label}\n")
    print(
        f"{'naif':>6} {'parent':>6} {'name':<14} {'a/R':>7} "
        f"{'i_eq°':>6} "
        + " ".join(f"{f'A_{d:g}d_km':>13}" for d in HORIZONS_DAYS)
        + " "
        + " ".join(f"{f'B_{d:g}d_km':>13}" for d in HORIZONS_DAYS)
        + " "
        + " ".join(f"{f'A/B_{d:g}d':>10}" for d in HORIZONS_DAYS)
    )

    grouped: dict[int, list[tuple[float, ...]]] = {}
    skipped_no_j2: list[str] = []
    skipped_other: list[tuple[str, str]] = []

    for naif_id, parent, name in moons:
        if name.lower() in CHEBYSHEV_MOON_WHITELIST:
            continue  # whitelisted — uses Chebyshev, not relevant
        gravity = parent_j2_r_eq(parent)
        if gravity is None:
            skipped_no_j2.append(name or str(naif_id))
            continue
        j2, r_eq = gravity
        mu = parent_mu(parent)
        if mu is None:
            skipped_other.append((name or str(naif_id), "no parent mu"))
            continue

        # Truth state at epoch (ecliptic) and rotation matrix
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

        # J2 rates for Method B, in equatorial frame
        om_dot, w_dot = j2_rates(elts_eq, j2, r_eq)
        elts_eq.om_dot_rad_s = om_dot
        elts_eq.w_dot_rad_s = w_dot

        # Per-horizon error
        a_over_r = elts_eq.a_km / r_eq
        i_eq_deg = math.degrees(elts_eq.i_rad)
        errs_a = []
        errs_b = []
        ratios = []
        for d in HORIZONS_DAYS:
            et_t = et0 + d * S_PER_DAY
            truth_state, _ = spiceypy.spkezr(
                str(naif_id), et_t, "ECLIPJ2000", "NONE", str(parent)
            )
            truth_ecl = np.asarray(truth_state[:3])
            pos_a = propagate_elements(elts_ecl, et_t)
            pos_b_eq = propagate_elements(elts_eq, et_t)
            pos_b_ecl = rot.T @ pos_b_eq
            err_a = float(np.linalg.norm(pos_a - truth_ecl))
            err_b = float(np.linalg.norm(pos_b_ecl - truth_ecl))
            errs_a.append(err_a)
            errs_b.append(err_b)
            ratios.append(err_a / err_b if err_b > 0 else float("inf"))

        print(
            f"{naif_id:>6} {parent:>6} {(name or '')[:14]:<14} "
            f"{a_over_r:>7.2f} {i_eq_deg:>6.1f} "
            + " ".join(f"{v:>13.3g}" for v in errs_a)
            + " "
            + " ".join(f"{v:>13.3g}" for v in errs_b)
            + " "
            + " ".join(f"{r:>10.2f}" for r in ratios)
        )
        grouped.setdefault(parent, []).append((a_over_r, *errs_a, *errs_b, *ratios))

    print(
        f"\nSkipped {len(skipped_no_j2)} moons (parent has no J2): "
        f"{', '.join(skipped_no_j2[:8])}{'...' if len(skipped_no_j2) > 8 else ''}"
    )
    if skipped_other:
        print(
            f"Skipped {len(skipped_other)} moons (other): "
            f"{', '.join(name for name, _ in skipped_other[:8])}"
            f"{'...' if len(skipped_other) > 8 else ''}"
        )

    # Per-parent summary: median error and median improvement at each horizon
    print("\nPer-parent medians:")
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
    print(
        f"{'parent':<10} {'count':>5} "
        + " ".join(f"{f'medA_{d:g}d':>12}" for d in HORIZONS_DAYS)
        + " "
        + " ".join(f"{f'medB_{d:g}d':>12}" for d in HORIZONS_DAYS)
        + " "
        + " ".join(f"{f'medA/B_{d:g}d':>12}" for d in HORIZONS_DAYS)
    )
    for parent, rows in sorted(grouped.items()):
        if not rows:
            continue
        a_cols = list(zip(*rows))
        # offsets: 0 = a/R, 1..n_h = errs_a, n_h+1..2n_h = errs_b, then ratios
        meds_a = [statistics.median(a_cols[1 + j]) for j in range(n_h)]
        meds_b = [statistics.median(a_cols[1 + n_h + j]) for j in range(n_h)]
        meds_r = [statistics.median(a_cols[1 + 2 * n_h + j]) for j in range(n_h)]
        label = parent_names.get(parent, str(parent))
        print(
            f"{label:<10} {len(rows):>5} "
            + " ".join(f"{v:>12.3g}" for v in meds_a)
            + " "
            + " ".join(f"{v:>12.3g}" for v in meds_b)
            + " "
            + " ".join(f"{r:>12.2f}" for r in meds_r)
        )

    # Distribution of A/B ratio at the 5y horizon, banded by a/R_parent
    bands = [(0, 5), (5, 15), (15, 50), (50, float("inf"))]
    print("\nA/B ratio at 5y horizon, by a/R_parent band:")
    print(f"{'a/R band':<14} {'count':>5} {'p25':>8} {'p50':>8} {'p75':>8}")
    h5_idx = HORIZONS_DAYS.index(5 * 365.25)
    for lo, hi in bands:
        ratios = []
        for rows in grouped.values():
            for r in rows:
                a_over_r = r[0]
                if lo <= a_over_r < hi:
                    ratios.append(r[1 + 2 * n_h + h5_idx])
        if not ratios:
            continue
        ratios.sort()
        p25 = ratios[len(ratios) // 4]
        p50 = ratios[len(ratios) // 2]
        p75 = ratios[(3 * len(ratios)) // 4]
        label = f"[{lo}, {hi if hi != float('inf') else '∞'})"
        print(f"{label:<14} {len(ratios):>5} {p25:>8.2f} {p50:>8.2f} {p75:>8.2f}")

    spiceypy.kclear()


if __name__ == "__main__":
    main()
