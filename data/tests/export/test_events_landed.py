"""Events-driven landed phases, from the plan to the packed record."""

import struct

from space_map_data.constants.providers import ID_TYPES
from space_map_data.export.position.format import (
    ID_TYPE_ORDINAL,
    LANDED_FLAG_STATIC,
    LANDED_HEADER_SIZE,
    LANDED_SAMPLE_SIZE,
    pack_landed_payload,
)
from space_map_data.export.position.probes.events_classify import (
    classify_events_phases,
)
from space_map_data.export.position.probes.landed import sited_landed_chunk
from space_map_data.export.position.probes.plan import ProbeMeta, zone_for_landed_body
from space_map_data.export.position.probes.time_grid import landed_chunk_range
from space_map_data.probes.landing_events import LandingPhase
from space_map_data.utils.time import S_PER_DAY, jd_to_et

NAIF = ID_TYPE_ORDINAL[ID_TYPES.NAIF]
MARS = 499
ROVER = 113217538
START_JD = 2459000.5
ZONE = zone_for_landed_body(MARS)
assert ZONE is not None
CHUNK_DAYS = ZONE.chunk_days
CHUNK_S = CHUNK_DAYS * S_PER_DAY
T0 = jd_to_et(START_JD)


def _phase(*waypoints: tuple[float, float, float]) -> LandingPhase:
    return LandingPhase(
        probe_id=ROVER,
        probe_name="Zhurong",
        body_id_type=NAIF,
        body_id_value=MARS,
        lat_deg=25.066,
        lng_deg=109.925,
        start_et=T0 + 0.25 * CHUNK_S,
        end_et=T0 + 2.5 * CHUNK_S,
        site_name=None,
        destroyed=False,
        waypoints=waypoints,
    )


def _contributions(phase: LandingPhase):
    meta = ProbeMeta(ROVER, f"probe-{ROVER}", 0, False, 0)
    [plan], _ = classify_events_phases([phase], [], {ROVER: meta}, START_JD)
    return plan.contributions


class TestChunkSlices:
    """Each chunk of a landed phase starts where the rover then stood."""

    def test_a_static_phase_keeps_its_site_in_every_chunk(self):
        slices = _contributions(_phase())
        assert len(slices) == 3
        assert {c.site_lat_lng for c in slices} == {(25.066, 109.925)}
        assert all(c.waypoints == () for c in slices)

    def test_a_waypoint_belongs_to_the_chunk_it_falls_in(self):
        first = (T0 + 0.5 * CHUNK_S, 25.065, 109.925)
        second = (T0 + 1.5 * CHUNK_S, 25.064, 109.926)
        a, b, c = _contributions(_phase(first, second))
        assert (a.site_lat_lng, a.waypoints) == ((25.066, 109.925), (first,))
        assert (b.site_lat_lng, b.waypoints) == ((25.065, 109.925), (second,))
        assert (c.site_lat_lng, c.waypoints) == ((25.064, 109.926), ())

    def test_the_slices_cover_the_phase(self):
        phase = _phase()
        slices = _contributions(phase)
        expected = landed_chunk_range(
            CHUNK_DAYS, phase.start_et, phase.end_et, START_JD
        )
        assert [(c.chunk_idx, c.c_start_et, c.c_end_et) for c in slices] == expected


class TestSitedLandedChunk:
    """The record of one chunk: the site, then one sample for each waypoint."""

    def _fit(self, waypoints=()):
        return sited_landed_chunk(
            body_id_value=MARS,
            body_id_type=NAIF,
            is_destroyed=False,
            chunk_start_et=T0,
            c_start_et=T0 + 100.0,
            c_end_et=T0 + CHUNK_S,
            site_lat_lng=(25.066, 109.925),
            waypoints=waypoints,
        )

    def test_a_chunk_with_no_waypoint_is_static(self):
        fit = self._fit()
        assert fit.is_static
        assert fit.samples == []
        assert (fit.lat_ref_deg, fit.lng_ref_deg) == (25.066, 109.925)
        assert fit.start_offset_s == 100
        assert fit.end_offset_s == round(CHUNK_S)

    def test_a_waypoint_is_a_sample_at_its_offset_from_the_chunk_start(self):
        fit = self._fit(((T0 + 5000.4, 25.065, 109.926),))
        assert not fit.is_static
        assert fit.samples == [(5000, 25.065, 109.926, 0.0)]

    def test_the_packed_record_carries_the_samples(self):
        fit = self._fit(((T0 + 5000.0, 25.065, 109.926),))
        payload = pack_landed_payload(
            body_id_value=fit.body_id_value,
            body_id_type=fit.body_id_type,
            is_static=fit.is_static,
            is_destroyed=fit.is_destroyed,
            start_offset_s=fit.start_offset_s,
            end_offset_s=fit.end_offset_s,
            lat_ref_deg=fit.lat_ref_deg,
            lng_ref_deg=fit.lng_ref_deg,
            alt_ref_m=fit.alt_ref_m,
            samples=fit.samples,
        )
        assert len(payload) == LANDED_HEADER_SIZE + LANDED_SAMPLE_SIZE
        flags = payload[4]
        assert not flags & LANDED_FLAG_STATIC
        lat_ref, lng_ref = struct.unpack_from("<ii", payload, 16)
        assert (lat_ref, lng_ref) == (250660000, 1099250000)
        offset_s, lat, lng, alt = struct.unpack_from(
            "<Iiii", payload, LANDED_HEADER_SIZE
        )
        assert (offset_s, lat, lng, alt) == (5000, 250650000, 1099260000, 0)

    def test_a_destroyed_site_stays_flagged(self):
        fit = sited_landed_chunk(
            body_id_value=MARS,
            body_id_type=NAIF,
            is_destroyed=True,
            chunk_start_et=T0,
            c_start_et=T0,
            c_end_et=T0 + 10.0,
            site_lat_lng=(0.0, 0.0),
            waypoints=(),
        )
        assert fit.is_destroyed and fit.is_static
