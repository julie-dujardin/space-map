"""The conic solve behind catalogue-derived trajectories.

Every case here is checked against geometry rather than against the catalogue:
a solved branch must genuinely pass through its anchor and genuinely carry the
elements it was given, or the arcs built on it mean nothing.
"""

import math

import numpy as np
import pytest
import spiceypy

from space_map_data.probes.deepcat import SolarElements
from space_map_data.probes.propagation import AU_KM
from space_map_data.probes.deepcat_solve import (
    GM_SUN,
    _node_solutions,
    _true_anomalies,
    solve_anchor,
)

# 1 x 1.5 AU, inclined — a plain Earth-to-Mars-ish transfer.
ELEMENTS = SolarElements(peri_au=1.0, apo_au=1.5, inc_deg=3.0, uncertain=False)
EARTH_LIKE_KM = np.array([1.0 * AU_KM, 0.0, 0.0])
EARTH_LIKE_VEL = np.array([0.0, 29.78, 0.0])


def _osculating(state: tuple[float, ...], epoch: float) -> tuple[float, float, float]:
    """Semi-major axis in AU, eccentricity and inclination in degrees."""
    elts = spiceypy.oscelt(np.array(list(state)), epoch, GM_SUN)
    rp, ecc = float(elts[0]), float(elts[1])
    return rp / (1.0 - ecc) / AU_KM, ecc, math.degrees(float(elts[2]))


class TestNodeSolutions:
    """The orbit plane has to contain the anchor."""

    def test_every_node_puts_the_anchor_in_the_plane(self):
        rng = np.random.default_rng(20260829)
        for _ in range(200):
            anchor = rng.normal(size=3) * 1e8
            inc = rng.uniform(0.05, math.pi - 0.05)
            for node in _node_solutions(anchor, inc):
                normal = np.array(
                    [
                        math.sin(inc) * math.sin(node),
                        -math.sin(inc) * math.cos(node),
                        math.cos(inc),
                    ]
                )
                assert abs(normal @ anchor) / np.linalg.norm(anchor) < 1e-9

    def test_two_planes_of_a_given_inclination_hold_any_anchor(self):
        assert len(_node_solutions(np.array([1e8, 2e8, 3e7]), 0.5)) == 2

    def test_an_anchor_too_far_off_the_ecliptic_admits_no_plane(self):
        # A 1-degree orbit cannot reach a point 45 degrees above the ecliptic.
        steep = np.array([1e8, 0.0, 1e8])
        assert _node_solutions(steep, math.radians(1.0)) == []

    def test_an_uninclined_orbit_has_no_line_of_nodes_to_solve(self):
        assert _node_solutions(np.array([1e8, 0.0, 0.0]), 1e-9) == [0.0]


class TestTrueAnomalies:
    """Where on the conic the anchor sits."""

    def test_a_radius_between_the_apsides_gives_a_symmetric_pair(self):
        a, ecc = 2.0 * AU_KM, 0.5
        outbound, inbound = _true_anomalies(2.0 * AU_KM, a, ecc, 0.0)
        assert math.isclose(outbound + inbound, 2 * math.pi, abs_tol=1e-9)

    def test_an_anchor_beyond_aphelion_is_rejected_without_tolerance(self):
        assert _true_anomalies(4.0 * AU_KM, 2.0 * AU_KM, 0.5, 0.0) == []

    def test_a_near_miss_within_tolerance_snaps_to_the_apsis(self):
        a, ecc = 2.0 * AU_KM, 0.5
        apo = a * (1 + ecc)
        assert _true_anomalies(apo * 1.001, a, ecc, apo * 0.01) == [math.pi]
        peri = a * (1 - ecc)
        assert _true_anomalies(peri * 0.999, a, ecc, peri * 0.01) == [0.0]

    def test_snapping_does_not_rescue_a_real_mismatch(self):
        assert _true_anomalies(4.0 * AU_KM, 2.0 * AU_KM, 0.5, 1e5) == []


class TestSolveAnchor:
    """A solved branch must reproduce both its anchor and its elements."""

    def test_every_branch_passes_through_the_anchor(self):
        solutions, failure = solve_anchor(ELEMENTS, EARTH_LIKE_KM, EARTH_LIKE_VEL, 0.0)
        assert failure is None
        assert solutions
        for s in solutions:
            assert np.linalg.norm(s.position_km - EARTH_LIKE_KM) < 1.0

    def test_every_branch_carries_the_given_elements(self):
        solutions, _ = solve_anchor(ELEMENTS, EARTH_LIKE_KM, EARTH_LIKE_VEL, 0.0)
        for s in solutions:
            a_au, ecc, inc = _osculating(s.state_km_kms, 0.0)
            assert math.isclose(a_au, ELEMENTS.semi_major_au, rel_tol=1e-6)
            assert math.isclose(ecc, ELEMENTS.eccentricity, rel_tol=1e-6)
            assert math.isclose(inc, ELEMENTS.inc_deg, rel_tol=1e-6)

    def test_branches_come_back_ordered_by_departure_speed(self):
        solutions, _ = solve_anchor(ELEMENTS, EARTH_LIKE_KM, EARTH_LIKE_VEL, 0.0)
        assert [s.vinf_kms for s in solutions] == sorted(s.vinf_kms for s in solutions)

    def test_an_anchor_outside_the_conic_reports_which_way(self):
        far = np.array([5.0 * AU_KM, 0.0, 0.0])
        solutions, failure = solve_anchor(ELEMENTS, far, EARTH_LIKE_VEL, 0.0)
        assert solutions == []
        assert failure is not None
        assert failure.reason == "radius_outside_conic"

    def test_an_inclination_that_cannot_reach_the_anchor_is_reported(self):
        polar_anchor = np.array([0.7 * AU_KM, 0.0, 0.7 * AU_KM])
        elements = SolarElements(1.0, 1.0, 1.0, uncertain=False)
        _, failure = solve_anchor(elements, polar_anchor, EARTH_LIKE_VEL, 0.0)
        assert failure is not None
        assert failure.reason == "plane_excludes_anchor"

    def test_an_escape_trajectory_is_not_solvable_from_apsides(self):
        # GCAT writes an aphelion for bound orbits only; a negative or absurd
        # pair would otherwise produce a silent nonsense conic.
        _, failure = solve_anchor(
            SolarElements(0.0, 0.0, 0.0, uncertain=False),
            EARTH_LIKE_KM,
            EARTH_LIKE_VEL,
            0.0,
        )
        assert failure is not None
        assert failure.reason == "unbound"

    def test_a_branch_demanding_an_impossible_departure_is_flagged(self):
        # An anchor moving the wrong way makes every branch cost tens of km/s.
        retrograde = np.array([0.0, -200.0, 0.0])
        solutions, failure = solve_anchor(
            ELEMENTS, np.array([1.2 * AU_KM, 0.0, 0.0]), retrograde, 0.0
        )
        assert solutions == []
        assert failure is not None
        assert failure.reason == "no_plausible_branch"


@pytest.mark.parametrize("inc_deg", [0.0, 0.5, 20.0])
def test_anchors_are_reproduced_across_the_inclination_range(inc_deg):
    """Near-zero inclination degenerates the node solve; the plane is then the
    ecliptic and the anchor's own longitude has to carry the orientation."""
    elements = SolarElements(0.9, 1.4, inc_deg, uncertain=False)
    anchor = np.array([0.8 * AU_KM, 0.6 * AU_KM, 0.0])
    solutions, failure = solve_anchor(elements, anchor, EARTH_LIKE_VEL, 0.0)
    assert failure is None
    assert solutions
    for s in solutions:
        assert np.linalg.norm(s.position_km - anchor) < 1.0


@pytest.mark.parametrize("inc_deg", [45.0, 90.0, 179.0])
def test_a_steeply_inclined_orbit_is_unreachable_from_a_prograde_anchor(inc_deg):
    """Cranking the plane over costs speed no departure has. The geometry is
    still solvable, so this is the departure-speed veto doing its job."""
    elements = SolarElements(0.9, 1.4, inc_deg, uncertain=False)
    anchor = np.array([0.8 * AU_KM, 0.6 * AU_KM, 0.0])
    solutions, failure = solve_anchor(elements, anchor, EARTH_LIKE_VEL, 0.0)
    assert solutions == []
    assert failure is not None
    assert failure.reason == "no_plausible_branch"
