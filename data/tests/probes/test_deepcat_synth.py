"""Writing catalogue-derived arcs into SPK kernels.

A written kernel has to give back the state it was seeded with, and has to
stop claiming a position where the arc stops — an open phase that propagated
forever would read downstream as coverage the catalogue never supported.
"""

import math

import numpy as np
import pytest
import spiceypy

from space_map_data.download.providers.spice.probes import deepcat_synth
from space_map_data.download.providers.spice.probes.deepcat_synth import (
    OPEN_ARC_YEARS,
    _segment_bounds,
    arc_segments,
)
from space_map_data.download.providers.spice.probes.synthetic_index import write_type5
from space_map_data.probes.propagation import AU_KM
from space_map_data.probes.deepcat_arcs import ArcClass, SolvedArc
from space_map_data.probes.deepcat_solve import GM_SUN, ConicSolution

NAIF = -90000123
STATE = (1.0 * AU_KM, 0.0, 0.0, 0.0, 32.0, 1.5)
YEAR_S = 365.25 * 86400.0


def _arc(arc_class, start_et, end_et):
    return SolvedArc(
        deep_id="D00088",
        name="Venera-2",
        phase=4,
        arc_class=arc_class,
        anchor_body="Earth",
        arrival_body="Venus" if arc_class is ArcClass.TRANSFER else None,
        start_et=start_et,
        end_et=end_et,
        solution=ConicSolution(STATE, start_et, 3.1),
        miss_hill=2.0 if arc_class is ArcClass.TRANSFER else None,
    )


class TestSegmentBounds:
    """How long each class of arc is claimed for."""

    def test_a_bounded_phase_is_claimed_exactly_as_long_as_it_lasts(self):
        assert _segment_bounds(_arc(ArcClass.TRANSFER, 0.0, 100.0)) == (0.0, 100.0)

    def test_an_open_phase_stops_at_the_measured_horizon(self):
        first, last = _segment_bounds(_arc(ArcClass.OPEN, 0.0, None))
        assert math.isclose(last - first, OPEN_ARC_YEARS * YEAR_S)


class TestWrittenKernel:
    """What SPICE reads back out."""

    @pytest.fixture
    def kernel(self, tmp_path):
        path = tmp_path / f"{NAIF}-extrap.bsp"
        arcs = [
            _arc(ArcClass.TRANSFER, 0.0, 90.0 * 86400.0),
            _arc(ArcClass.OPEN, 120.0 * 86400.0, None),
        ]
        write_type5(path, NAIF, "gcat", arc_segments(arcs, "Venera-2"))
        spiceypy.furnsh(str(path))
        yield path
        spiceypy.unload(str(path))
        spiceypy.kclear()

    def test_the_seed_state_comes_back_at_its_own_epoch(self, kernel):
        state, _ = spiceypy.spkezr(str(NAIF), 0.0, "ECLIPJ2000", "NONE", "10")
        assert np.allclose(np.asarray(state), np.array(STATE), rtol=1e-9)

    def test_the_arc_is_two_body_between_its_ends(self, kernel):
        et = 40.0 * 86400.0
        state, _ = spiceypy.spkezr(str(NAIF), et, "ECLIPJ2000", "NONE", "10")
        expected = spiceypy.prop2b(GM_SUN, np.array(STATE), et)
        assert np.allclose(np.asarray(state)[:3], np.asarray(expected)[:3], rtol=1e-6)

    def test_each_phase_gets_its_own_segment(self, kernel):
        cell = spiceypy.cell_double(200)
        spiceypy.spkcov(str(kernel), NAIF, cell)
        assert spiceypy.wncard(cell) == 2

    def test_nothing_is_claimed_past_the_last_arc(self, kernel):
        beyond = (120.0 * 86400.0) + (OPEN_ARC_YEARS + 1.0) * YEAR_S
        with pytest.raises(spiceypy.exceptions.SpiceyError):
            spiceypy.spkezr(str(NAIF), beyond, "ECLIPJ2000", "NONE", "10")

    def test_rewriting_replaces_rather_than_appends(self, tmp_path):
        path = tmp_path / f"{NAIF}-extrap.bsp"
        segments = arc_segments([_arc(ArcClass.TRANSFER, 0.0, 100.0)], "Venera-2")
        for _ in range(2):
            write_type5(path, NAIF, "gcat", segments)
        cell = spiceypy.cell_double(200)
        spiceypy.spkcov(str(path), NAIF, cell)
        assert spiceypy.wncard(cell) == 1


class TestArcHash:
    """Idempotence: a rerun rewrites only what actually changed."""

    def test_the_same_arcs_hash_the_same(self):
        arcs = [_arc(ArcClass.TRANSFER, 0.0, 100.0)]
        assert deepcat_synth._arc_hash(NAIF, arcs) == deepcat_synth._arc_hash(
            NAIF, arcs
        )

    def test_a_moved_boundary_changes_the_hash(self):
        before = deepcat_synth._arc_hash(NAIF, [_arc(ArcClass.TRANSFER, 0.0, 100.0)])
        after = deepcat_synth._arc_hash(NAIF, [_arc(ArcClass.TRANSFER, 0.0, 200.0)])
        assert before != after
