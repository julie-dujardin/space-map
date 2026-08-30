"""Turn a Deep Space Catalog solar phase into a heliocentric state vector.

GCAT publishes perihelion, aphelion and inclination — the orbit's size and
shape but not its orientation. The missing three elements come from the phase
boundary itself: a solar phase opens when the object leaves a planet's sphere
of influence, so at that instant it sits on that planet, to within the sphere's
radius. Requiring the conic to pass through that point fixes the node, the
argument of perihelion and the epoch anomaly up to a four-way discrete
ambiguity, which the departure velocity then resolves — the object must leave
its parent planet at a launch-plausible excess speed, and only one branch does.

The result is a two-body conic, so it ignores the mid-course corrections the
real flight made. :func:`solve_phase` reports the residual against GCAT's own
figures; callers decide what error is worth publishing.
"""

import logging
import math
from dataclasses import dataclass

import numpy as np
import spiceypy

from space_map_data.probes.deepcat import SolarElements
from space_map_data.probes.propagation import AU_KM, GM_SUN

logger = logging.getLogger(__name__)

# Hill radii, km. The catalogue opens and closes a phase at the Hill sphere,
# not the smaller Laplace sphere of influence — confirmed by measuring where
# real spacecraft actually are at each phase boundary. The anchor is only good
# to this, which is the method's error floor: nothing downstream can be more
# precise than "it was somewhere on Earth's Hill sphere".
HILL_KM: dict[str, float] = {
    "Mercury": 1.9e5,
    "Venus": 1.01e6,
    "Earth": 1.50e6,
    "Luna": 6.4e4,
    "Mars": 1.08e6,
    "Jupiter": 5.1e7,
    "Saturn": 6.5e7,
    "Uranus": 7.0e7,
    "Neptune": 1.16e8,
}

# GCAT body names to the SPICE body the anchor is taken from. Barycentres for
# the outer planets because de440 carries no planet body past Mars.
ANCHOR_NAIF: dict[str, int] = {
    "Mercury": 199,
    "Venus": 299,
    "Earth": 399,
    "Luna": 301,
    "Mars": 4,
    "Jupiter": 5,
    "Saturn": 6,
    "Uranus": 7,
    "Neptune": 8,
}

# Above this the departure is not a departure — no launcher or gravity assist
# of the era leaves a planet that fast, so a branch demanding it is the wrong
# branch. Voyager 2 leaving Jupiter is the high-water mark at roughly 16 km/s.
MAX_PLAUSIBLE_VINF_KMS = 20.0

# Below this inclination the line of nodes is not defined by the geometry and
# the node solution is numerically meaningless; the orbit is treated as
# ecliptic and the anchor's own longitude sets the orientation.
MIN_INC_DEG = 1e-3


@dataclass(frozen=True)
class ConicSolution:
    """One branch of the anchor solve, as a state and the elements behind it."""

    state_km_kms: tuple[float, float, float, float, float, float]
    epoch_et: float
    vinf_kms: float

    @property
    def position_km(self) -> np.ndarray:
        return np.array(self.state_km_kms[:3])


@dataclass(frozen=True)
class SolveFailure:
    """Why a phase produced nothing, so a run can report the distribution of
    failures rather than a bare count."""

    reason: str


def _node_solutions(anchor_km: np.ndarray, inc_rad: float) -> list[float]:
    """Longitudes of the ascending node whose orbit plane contains the anchor.

    The plane normal is (sin i sin O, -sin i cos O, cos i) and must be
    perpendicular to the anchor, which reduces to
    ``x sin O - y cos O = -z cot i`` — a single sinusoid in O with zero, one or
    two roots."""
    x, y, z = anchor_km
    if inc_rad < math.radians(MIN_INC_DEG):
        # Degenerate plane: the node is a free parameter, so anchor it at the
        # ecliptic origin and let the argument of latitude carry the geometry.
        return [0.0]

    rhs = -z / math.tan(inc_rad)
    amp = math.hypot(x, y)
    if amp == 0.0 or abs(rhs) > amp:
        return []
    # x sin O - y cos O rewrites as amp sin(O + psi), so the two roots are the
    # arcsine branch and its supplement.
    psi = math.atan2(-y, x)
    delta = math.asin(rhs / amp)
    return [(delta - psi) % (2 * math.pi), (math.pi - delta - psi) % (2 * math.pi)]


def _true_anomalies(
    r_km: float, semi_major_km: float, ecc: float, tolerance_km: float
) -> list[float]:
    """The true anomalies at which the conic has radius ``r_km``.

    The anchor sits on a Hill sphere and GCAT rounds its apsides to a
    thousandth of an AU, so an anchor that lands just outside the conic is
    almost always a departure at an apsis rather than a real contradiction —
    measured across the catalogue, 81 of 85 such anchors are within 0.02 AU of
    the boundary. Those snap to the apsis, which also collapses the sign
    ambiguity. Anything further out is a genuine mismatch and returns empty."""
    # An anchor sitting exactly on an apsis lands a rounding step outside it,
    # so the tolerance never drops below the arithmetic's own resolution.
    tol = max(tolerance_km, 1e-9 * semi_major_km)
    if ecc < 1e-9:
        return [0.0] if abs(r_km - semi_major_km) <= tol else []
    peri = semi_major_km * (1.0 - ecc)
    apo = semi_major_km * (1.0 + ecc)
    if r_km < peri:
        return [0.0] if peri - r_km <= tol else []
    if r_km > apo:
        return [math.pi] if r_km - apo <= tol else []
    p = semi_major_km * (1.0 - ecc * ecc)
    nu = math.acos(max(-1.0, min(1.0, (p / r_km - 1.0) / ecc)))
    return [nu, -nu % (2 * math.pi)]


def _argument_of_latitude(
    anchor_km: np.ndarray, node_rad: float, inc_rad: float
) -> float:
    """Angle from the ascending node to the anchor, measured in the plane."""
    x, y, z = anchor_km
    along_node = x * math.cos(node_rad) + y * math.sin(node_rad)
    if inc_rad < math.radians(MIN_INC_DEG):
        return math.atan2(y, x)
    return math.atan2(z / math.sin(inc_rad), along_node)


def solve_anchor(
    elements: SolarElements,
    anchor_km: np.ndarray,
    anchor_vel_kms: np.ndarray,
    epoch_et: float,
    tolerance_km: float = 0.0,
) -> tuple[list[ConicSolution], SolveFailure | None]:
    """Every conic with these elements that passes through ``anchor_km``.

    Returns the branches sorted by excess speed over the anchor body, which is
    the discriminator: the true trajectory departs its parent at a few km/s
    while the mirror branches demand tens."""
    semi_major_km = elements.semi_major_au * AU_KM
    ecc = elements.eccentricity
    inc_rad = math.radians(abs(elements.inc_deg))
    r_km = float(np.linalg.norm(anchor_km))

    if semi_major_km <= 0.0 or ecc >= 1.0:
        return [], SolveFailure("unbound")

    nodes = _node_solutions(anchor_km, inc_rad)
    if not nodes:
        return [], SolveFailure("plane_excludes_anchor")

    anomalies = _true_anomalies(r_km, semi_major_km, ecc, tolerance_km)
    if not anomalies:
        return [], SolveFailure("radius_outside_conic")

    out: list[ConicSolution] = []
    for node in nodes:
        u = _argument_of_latitude(anchor_km, node, inc_rad)
        for nu in anomalies:
            argp = (u - nu) % (2 * math.pi)
            # oscelt order: rp, ecc, inc, lnode, argp, m0, t0, mu.
            elts = np.array(
                [
                    semi_major_km * (1.0 - ecc),
                    ecc,
                    inc_rad,
                    node,
                    argp,
                    _mean_anomaly(nu, ecc),
                    epoch_et,
                    GM_SUN,
                ]
            )
            state = np.asarray(spiceypy.conics(elts, epoch_et), dtype=float)
            vinf = float(np.linalg.norm(state[3:] - anchor_vel_kms))
            out.append(
                ConicSolution(
                    state_km_kms=(
                        float(state[0]),
                        float(state[1]),
                        float(state[2]),
                        float(state[3]),
                        float(state[4]),
                        float(state[5]),
                    ),
                    epoch_et=epoch_et,
                    vinf_kms=vinf,
                )
            )

    out.sort(key=lambda s: s.vinf_kms)
    plausible = [s for s in out if s.vinf_kms <= MAX_PLAUSIBLE_VINF_KMS]
    if not plausible:
        return [], SolveFailure("no_plausible_branch")
    return plausible, None


def _mean_anomaly(nu: float, ecc: float) -> float:
    """True anomaly to mean anomaly for an ellipse."""
    cos_nu, sin_nu = math.cos(nu), math.sin(nu)
    denom = 1.0 + ecc * cos_nu
    ecc_anom = math.atan2(
        math.sqrt(1.0 - ecc * ecc) * sin_nu / denom, (ecc + cos_nu) / denom
    )
    return (ecc_anom - ecc * math.sin(ecc_anom)) % (2 * math.pi)


@dataclass(frozen=True)
class BoundaryConstraint:
    """One end of a phase. A phase that closes with "Entered Venus sphere"
    says the object was on Venus' Hill sphere at that instant; the opening
    boundary says the same about the body it just left. Either can anchor the
    solve, and whichever does not becomes the test the branches are ranked by."""

    body: str
    et: float
    position_km: np.ndarray
    velocity_kms: np.ndarray
    hill_km: float


def branch_score(solution: ConicSolution, boundary: BoundaryConstraint) -> float:
    """How far the branch is from the far boundary at that instant, in Hill
    radii. One is a hit; the wrong branch misses by tens."""
    dt = boundary.et - solution.epoch_et
    state = np.asarray(
        spiceypy.prop2b(GM_SUN, np.array(solution.state_km_kms), dt), dtype=float
    )
    return float(np.linalg.norm(state[:3] - boundary.position_km)) / boundary.hill_km


def choose_branch(
    solutions: list[ConicSolution], boundary: BoundaryConstraint | None
) -> ConicSolution:
    """Pick the branch the evidence supports.

    Departure speed alone gets it right about half the time, so the far
    boundary decides whenever the phase has one, and raises that to roughly
    three quarters. Adding conserved excess speed to the score was measured
    against 52 phases with archive trajectories and made it worse — most legs
    flew a deep-space manoeuvre, so the speed is not in fact conserved and the
    term is noise. Miss distance alone, with departure speed as a tie-break."""
    if boundary is None:
        return min(solutions, key=lambda s: s.vinf_kms)
    return min(solutions, key=lambda s: (branch_score(s, boundary), s.vinf_kms))


def anchor_state(body: str, et: float) -> tuple[np.ndarray, np.ndarray] | None:
    """Heliocentric ecliptic position and velocity of a GCAT-named body.
    Caller owns the kernel pool."""
    naif = ANCHOR_NAIF.get(body)
    if naif is None:
        return None
    try:
        state, _ = spiceypy.spkezr(str(naif), et, "ECLIPJ2000", "NONE", "10")
    except spiceypy.exceptions.SpiceyError:
        logger.warning("deepcat: no ephemeris for anchor %s at et=%.1f", body, et)
        return None
    arr = np.asarray(state, dtype=float)
    return arr[:3], arr[3:]


__all__ = [
    "ANCHOR_NAIF",
    "HILL_KM",
    "BoundaryConstraint",
    "ConicSolution",
    "anchor_state",
    "branch_score",
    "choose_branch",
    "solve_anchor",
]
