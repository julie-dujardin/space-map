"""Ingenuity's traverse from the airfields and tracks of the location map."""

import pytest
import spiceypy

from space_map_data.download.providers.ingenuity import INGENUITY_DIR
from space_map_data.probes import ingenuity_traverse, traverses
from space_map_data.probes.events import event_jd
from space_map_data.probes.ingenuity_traverse import (
    Airfield,
    Track,
    flight_waypoints,
    flights,
    read_tracks,
)
from space_map_data.utils.time import jd_to_et, utc_jd_to_tdb

_LSK = """KPL/LSK
\\begindata
DELTET/DELTA_T_A = 32.184
DELTET/K = 1.657D-3
DELTET/EB = 1.671D-2
DELTET/M = ( 6.239996D0 1.99096871D-7 )
DELTET/DELTA_AT = ( 37, @2017-JAN-1 )
\\begintext
"""

A0 = Airfield(18.0, 77.0, 0.0)
A1 = Airfield(18.0, 77.001, 100.0)
A2 = Airfield(18.001, 77.001, 200.0)


def _track(start: Airfield, end: Airfield, takeoff: float, landing: float) -> Track:
    return Track(
        ((start.lon_deg, start.lat_deg), (end.lon_deg, end.lat_deg)), takeoff, landing
    )


def _feature(track: Track) -> dict:
    return {
        "properties": {
            "SCLK_START": track.takeoff_sclk,
            "SCLK_END": track.landing_sclk,
        },
        "geometry": {"coordinates": [list(p) for p in track.points]},
    }


class TestFlights:
    """The clock pairs each track with the airfields it flew between."""

    def test_tracks_follow_the_clock_not_the_file_order(self):
        first = _track(A0, A1, 50.0, 100.0)
        second = _track(A1, A2, 150.0, 200.0)
        raw = {"features": [_feature(second), _feature(first)]}
        assert flights([A0, A1, A2], read_tracks(raw)) == [(first, A1), (second, A2)]

    def test_a_track_that_misses_its_airfield_is_refused(self):
        off = Airfield(18.0, 77.0011, 100.0)
        with pytest.raises(ValueError, match="misses its airfield"):
            flights([A0, A1], [_track(A0, off, 50.0, 100.0)])

    @pytest.mark.parametrize("landing", [-1.0, 120.0])
    def test_a_track_that_does_not_land_in_its_flight_is_refused(self, landing):
        with pytest.raises(ValueError, match="does not land on airfield 1"):
            flights([A0, A1], [_track(A0, A1, 50.0, landing)])

    def test_two_tracks_in_one_rest_are_refused(self):
        tracks = [_track(A0, A1, 50.0, 60.0), _track(A0, A1, 70.0, 100.0)]
        with pytest.raises(ValueError, match="takes off after airfield"):
            flights([A0, A1, A2], tracks)

    def test_a_missing_track_is_refused(self):
        with pytest.raises(ValueError, match="1 tracks for 3 airfields"):
            flights([A0, A1, A2], [_track(A0, A1, 50.0, 100.0)])


class TestFlightWaypoints:
    """A waypoint each whole second along the track, then the airfield."""

    @pytest.fixture(autouse=True)
    def _lsk(self, tmp_path):
        path = tmp_path / "test.tls"
        path.write_text(_LSK)
        spiceypy.furnsh(str(path))
        yield
        spiceypy.kclear()

    def test_the_track_is_sampled_on_whole_seconds(self):
        takeoff = spiceypy.str2et("2021-04-19T07:34:09.5")
        track = _track(A0, A1, 0.0, 0.0)
        out = flight_waypoints(track, A1, takeoff, takeoff + 10.0)
        times = [spiceypy.et2utc(et, "ISOC", 3) for et, _, _ in out]
        assert times[0] == "2021-04-19T07:34:10.000"
        assert times[-1] == "2021-04-19T07:34:20.000"
        assert len(times) == 11

    def test_samples_are_spread_evenly_between_the_two_ends(self):
        takeoff = spiceypy.str2et("2021-04-19T07:34:09.5")
        track = _track(A0, A1, 0.0, 0.0)
        _, lat, lon = flight_waypoints(track, A1, takeoff, takeoff + 10.0)[0]
        assert lat == pytest.approx(18.0)
        assert lon == pytest.approx(77.0 + 0.001 * 0.05)

    def test_the_last_waypoint_is_the_airfield(self):
        takeoff = spiceypy.str2et("2021-04-19T07:34:10")
        track = _track(A0, A1, 0.0, 0.0)
        assert flight_waypoints(track, A1, takeoff, takeoff + 3.5)[-1][1:] == (
            A1.lat_deg,
            A1.lon_deg,
        )


@pytest.mark.data
class TestDownloadedMap:
    """The downloaded map makes a valid traverse."""

    def test_the_helicopter_ends_at_its_last_airfield(self, tmp_path):
        ingenuity_traverse.build(INGENUITY_DIR, tmp_path)
        traverse = traverses.load_traverses(tmp_path)[ingenuity_traverse.PROBE_ID]
        assert traverse.sources == ingenuity_traverse.SOURCES
        last = traverse.waypoints[-1]
        assert (last.lat_deg, last.lon_deg) == (18.49726866, 77.32253449)

    def test_the_first_flight_takes_off_at_734_utc(self, tmp_path):
        """NASA gives 07:34 UTC on 19 April 2021 for the first flight."""
        ingenuity_traverse.build(INGENUITY_DIR, tmp_path)
        traverse = traverses.load_traverses(tmp_path)[ingenuity_traverse.PROBE_ID]
        et = jd_to_et(traverse.waypoints[0].jd)
        minute = [
            jd_to_et(utc_jd_to_tdb(event_jd(t)))
            for t in ("2021-04-19T07:34:00Z", "2021-04-19T07:35:00Z")
        ]
        assert minute[0] <= et < minute[1]
