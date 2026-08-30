"""Which catalogue phases become published trajectories.

The policy here was set by measuring 57 phases against archive trajectories,
so each rule is a claim about accuracy and is pinned as such. Anchor
ephemerides are stubbed: the geometry is covered in the solver tests, and what
matters here is which phases are let through.
"""

import numpy as np
import pytest

from space_map_data.probes import deepcat_arcs
from space_map_data.probes.deepcat import (
    DeepObject,
    DeepPhase,
    parse_gcat_date,
    parse_solar_elements,
)
from space_map_data.probes.propagation import AU_KM
from space_map_data.probes.deepcat_arcs import ArcClass, solve_object

OBJ = DeepObject("D00088", "S01730", "1965 091A", "Venera-2", "1965 Nov 12")
ELEMENTS = parse_solar_elements("0.718 x 1.019 AU x 0.58")

# Positions a Venus transfer can actually be solved against, and velocities
# that make the departure look like a launch rather than an impossibility.
STUB_BODIES = {
    "Earth": (np.array([1.0 * AU_KM, 0.0, 0.0]), np.array([0.0, 29.8, 0.0])),
    "Venus": (np.array([0.0, -0.72 * AU_KM, 0.0]), np.array([35.0, 0.0, 0.0])),
    "Jupiter": (np.array([0.0, 5.2 * AU_KM, 0.0]), np.array([-13.1, 0.0, 0.0])),
}


@pytest.fixture(autouse=True)
def stub_anchors(monkeypatch):
    monkeypatch.setattr(
        deepcat_arcs, "anchor_state", lambda body, et: STUB_BODIES.get(body)
    )


def _phase(number, body, start, end="", dest="", orbit="0.718 x 1.019 AU x 0.58"):
    return DeepPhase(
        deep_id=OBJ.deep_id,
        name=OBJ.name,
        phase=number,
        body=body,
        start=parse_gcat_date(start),
        end=parse_gcat_date(end),
        dest=dest,
        epoch=None,
        elements=parse_solar_elements(orbit),
    )


def _reasons(rows):
    return {r.reason for r in solve_object(OBJ, rows)[1]}


class TestPublishedArcs:
    """The two shapes that survived measurement."""

    # Venera 2's shape: Earth phases, the cruise, the Venus encounter, then
    # the derelict heliocentric orbit it is still on.
    ROWS = [
        _phase(0, "Earth", "1965 Nov 12 0446"),
        _phase(4, "Sun", "1965 Nov 13", "1966 Feb 26", "Entered Venus sphere"),
        _phase(5, "Venus", "1966 Feb 26", "1966 Feb 27 0252", "Flyby Venus"),
        _phase(7, "Sun", "1966 Feb 28", "-", "In solar orbit"),
    ]

    def test_a_bounded_leg_between_two_bodies_is_a_transfer(self):
        arcs, _ = solve_object(OBJ, self.ROWS)
        transfer = next(a for a in arcs if a.phase == 4)
        assert transfer.arc_class is ArcClass.TRANSFER
        assert (transfer.anchor_body, transfer.arrival_body) == ("Earth", "Venus")
        assert transfer.end_et is not None
        assert transfer.miss_hill is not None

    def test_a_phase_that_never_ends_is_an_open_arc(self):
        arcs, _ = solve_object(OBJ, self.ROWS)
        open_arc = next(a for a in arcs if a.phase == 7)
        assert open_arc.arc_class is ArcClass.OPEN
        assert open_arc.end_et is None
        assert open_arc.arrival_body is None

    def test_a_transfer_is_claimed_more_precisely_than_an_open_arc(self):
        arcs, _ = solve_object(OBJ, self.ROWS)
        by_class = {a.arc_class: a for a in arcs}
        assert (
            by_class[ArcClass.TRANSFER].median_error_au
            < by_class[ArcClass.OPEN].median_error_au
        )

    def test_earth_orbit_phases_are_not_arcs_at_all(self):
        arcs, _ = solve_object(OBJ, self.ROWS)
        assert all(a.phase != 0 for a in arcs)


class TestDeclinedPhases:
    """Each rejection stands for a measured accuracy cliff."""

    def test_a_phase_with_no_published_orbit(self):
        rows = [
            _phase(0, "Earth", "1965 Nov 12"),
            _phase(4, "Sun", "1965 Nov 13", orbit=""),
        ]
        assert "no_elements" in _reasons(rows)

    def test_a_start_date_known_only_to_the_month(self):
        rows = [_phase(0, "Earth", "1965 Nov 12"), _phase(4, "Sun", "1965 Nov")]
        assert "start_too_coarse" in _reasons(rows)

    def test_a_first_phase_has_nothing_to_have_departed_from(self):
        assert "no_anchor_body" in _reasons([_phase(4, "Sun", "1965 Nov 13")])

    def test_an_outer_planet_hill_sphere_is_too_coarse_to_anchor(self):
        rows = [_phase(0, "Jupiter", "1974 Dec 2"), _phase(4, "Sun", "1974 Dec 4")]
        assert "outer_anchor" in _reasons(rows)

    def test_a_loop_back_to_the_departure_body_is_dropped(self):
        # Gravity-assist returns carry the deep-space manoeuvre a single conic
        # cannot represent; measured error was ten times the transfer class.
        rows = [
            _phase(0, "Earth", "2005 Jan 12"),
            _phase(4, "Sun", "2005 Jan 14", "2007 Jan 31", "Entered Earth sphere"),
        ]
        assert "returns_to_anchor" in _reasons(rows)

    def test_elements_that_cannot_reach_the_departure_point(self):
        rows = [
            _phase(0, "Earth", "1965 Nov 12"),
            _phase(4, "Sun", "1965 Nov 13", orbit="4.000 x 5.000 AU x 0.58"),
        ]
        assert "no_conic_through_anchor" in _reasons(rows)


class TestArrivalHandling:
    """An arrival GCAT names but the solver cannot place."""

    def test_an_unplaceable_arrival_degrades_to_an_open_arc(self):
        rows = [
            _phase(0, "Earth", "2004 Mar 2"),
            _phase(4, "Sun", "2004 Mar 4", "2014 Aug 6", "Entered 67P/ sphere"),
        ]
        arcs, _ = solve_object(OBJ, rows)
        assert [a.arc_class for a in arcs] == [ArcClass.OPEN]
        assert arcs[0].arrival_body is None

    def test_an_arrival_date_too_coarse_to_use_degrades_the_same_way(self):
        rows = [
            _phase(0, "Earth", "1965 Nov 12"),
            _phase(4, "Sun", "1965 Nov 13", "1966", "Entered Venus sphere"),
        ]
        arcs, _ = solve_object(OBJ, rows)
        assert arcs[0].arc_class is ArcClass.OPEN
