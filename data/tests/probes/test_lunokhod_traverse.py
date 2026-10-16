"""Lunokhod traverses from the tables of the route papers."""

from pathlib import Path

from space_map_data.probes import lunokhod_traverse, traverses
from space_map_data.probes.events import event_jd
from space_map_data.probes.lunokhod_traverse import (
    LUNOKHOD_1,
    LUNOKHOD_2,
    Rover,
    Row,
    waypoints,
)


def _rover(*rows: Row) -> Rover:
    return Rover(1, ("karachevtseva_2017",), (25.0, 30.0), rows)


class TestWaypoints:
    """A waypoint for each new place, on the day the table gives."""

    def test_a_place_of_its_own_day_keeps_the_bare_date(self):
        rover = _rover(Row(("1973-02-11",), 25.1, 30.1))
        assert waypoints(rover) == [("1973-02-11", 25.1, 30.1)]

    def test_the_places_of_one_day_are_spread_over_it_in_table_order(self):
        rover = _rover(
            Row(("1973-02-12",), 25.1, 30.1), Row(("1973-02-12",), 25.2, 30.2)
        )
        assert [time for time, _, _ in waypoints(rover)] == [
            "1973-02-12T08:00Z",
            "1973-02-12T16:00Z",
        ]

    def test_a_later_row_of_the_same_place_refines_it(self):
        rover = _rover(
            Row(("1973-01-25",), 25.1, 30.1), Row(("1973-02-09",), 25.10001, 30.1)
        )
        assert waypoints(rover) == [("1973-01-25", 25.10001, 30.1)]

    def test_a_row_at_the_landing_site_is_not_a_move(self):
        rover = _rover(Row(("1973-01-16",), 25.00001, 30.0))
        assert waypoints(rover) == []

    def test_a_place_visited_twice_is_a_waypoint_each_time(self):
        rover = _rover(
            Row(("1973-02-19", "1973-03-13"), 25.1, 30.1),
            Row(("1973-03-12",), 25.2, 30.2),
        )
        assert [(time, lat) for time, lat, _ in waypoints(rover)] == [
            ("1973-02-19", 25.1),
            ("1973-03-12", 25.2),
            ("1973-03-13", 25.1),
        ]


class TestTables:
    """The transcribed tables make valid traverses."""

    def test_the_waypoints_are_in_time_order(self):
        for rover in (LUNOKHOD_1, LUNOKHOD_2):
            jds = [event_jd(time) for time, _, _ in waypoints(rover)]
            assert jds == sorted(set(jds))

    def test_each_rover_ends_at_its_final_place(self):
        assert waypoints(LUNOKHOD_2)[-1] == ("1973-05-10", 25.83233, 30.92211)
        # The final place of Lunokhod 1 is within 2 m of its tenth night, and
        # replaces it.
        assert waypoints(LUNOKHOD_1)[-1] == ("1971-08-17", 38.31516, -35.00796)

    def test_the_built_file_loads(self, tmp_path: Path):
        lunokhod_traverse.build(LUNOKHOD_2, tmp_path)
        loaded = traverses.load_traverses(tmp_path)[LUNOKHOD_2.probe_id]
        assert loaded.body_naif == 301
        assert (loaded.landing_lat_deg, loaded.landing_lon_deg) == LUNOKHOD_2.landing
        assert len(loaded.waypoints) == len(waypoints(LUNOKHOD_2))
