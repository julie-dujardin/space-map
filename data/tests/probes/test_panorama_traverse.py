"""Traverses in the frame of the panoramas: MER from its corrected traverse
table, the Viking landers at their published sites."""

import math
from pathlib import Path

import pytest

from space_map_data.panoramas import mer
from space_map_data.probes import panorama_traverse, traverses
from space_map_data.probes.events import event_jd
from space_map_data.probes.panorama_traverse import local_sol_date, rover_waypoints

# Opportunity touched down at 05:05 UTC, early afternoon of its sol 1.
LANDING_JD = event_jd("2004-01-25T05:05:00Z")
LON = mer.LANDING["opportunity"][1]
HEADER = "SITE,DRIVE,START_SOL,END_SOL,RAW_X,RAW_Y,RAW_Z,CORRECTED_X,CORRECTED_Y\n"


def _table(tmp_path: Path, *rows: tuple[int, int, int, int, float, float]) -> Path:
    path = tmp_path / "traverse.csv"
    path.write_text(
        HEADER
        + "".join(f"{s},{d},{a},{b},0,0,0,{x},{y}\n" for s, d, a, b, x, y in rows)
    )
    return path


def _sol_and_hour(time: str) -> tuple[int, float]:
    local = local_sol_date(event_jd(time), LON)
    first = math.floor(local_sol_date(LANDING_JD, LON))
    return math.floor(local) - first + 1, (local % 1) * 24


class TestRoverWaypoints:
    """Each new stop is a waypoint inside the sol that reached it."""

    def test_the_landing_row_is_not_a_move(self, tmp_path: Path):
        table = _table(tmp_path, (0, 0, 1, 1, 0, 0))
        assert rover_waypoints("opportunity", table, LANDING_JD) == []

    def test_a_stop_is_placed_by_its_offset_from_the_landing_site(self, tmp_path: Path):
        table = _table(tmp_path, (0, 0, 1, 1, 0, 0), (1, 0, 12, 14, 0, 100))
        [(_, lat, lon)] = rover_waypoints("opportunity", table, LANDING_JD)
        degree_m = mer.MARS_RADIUS_M * math.pi / 180
        assert lat == pytest.approx(mer.LANDING["opportunity"][0] + 100 / degree_m)
        assert lon == pytest.approx(LON)

    def test_the_stops_of_one_sol_share_its_drive_hours(self, tmp_path: Path):
        table = _table(
            tmp_path, (0, 0, 1, 1, 0, 0), (1, 1, 12, 12, 0, 10), (1, 2, 12, 13, 0, 20)
        )
        times = [
            time for time, _, _ in rover_waypoints("opportunity", table, LANDING_JD)
        ]
        (sol_a, hour_a), (sol_b, hour_b) = map(_sol_and_hour, times)
        assert (sol_a, sol_b) == (12, 12)
        assert hour_a == pytest.approx(11 + 4 / 3, abs=1e-3)
        assert hour_b == pytest.approx(11 + 8 / 3, abs=1e-3)

    def test_a_row_dated_before_the_row_above_keeps_the_order(self, tmp_path: Path):
        table = _table(
            tmp_path, (0, 0, 1, 1, 0, 0), (1, 1, 20, 20, 0, 10), (1, 2, 19, 21, 0, 20)
        )
        times = [
            time for time, _, _ in rover_waypoints("opportunity", table, LANDING_JD)
        ]
        assert times == sorted(times)
        assert [_sol_and_hour(t)[0] for t in times] == [20, 20]

    def test_a_stop_at_the_same_place_is_not_a_move(self, tmp_path: Path):
        table = _table(
            tmp_path, (0, 0, 1, 1, 0, 0), (1, 1, 5, 5, 0, 10), (1, 2, 6, 6, 0, 10)
        )
        assert len(rover_waypoints("opportunity", table, LANDING_JD)) == 1


class TestLanders:
    """A Viking lander gets a landing point and no waypoints."""

    def test_viking_one_stands_at_its_published_site(self, tmp_path: Path):
        panorama_traverse.build_lander("viking1", tmp_path)
        lander = traverses.load_traverses(tmp_path)[47378432]
        assert (lander.landing_lat_deg, lander.landing_lon_deg) == (22.27, 312.05)
        assert lander.body_naif == 499
        assert lander.waypoints == ()
