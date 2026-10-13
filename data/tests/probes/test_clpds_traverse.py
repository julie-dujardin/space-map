"""Rover traverses built from the labels of China's data release."""

from pathlib import Path

import pytest

from space_map_data.probes import clpds_traverse, traverses
from space_map_data.probes.clpds_traverse import Rover

MARS_ROVER = Rover("zhurong", 113217538, 499, 3389500.0, (-0.3, 4.3))
MOON_ROVER = Rover("yutu-2", 110784513, 301, 1737400.0)


def _mars_label(time: str, lat: float, lon: float) -> str:
    return f"""<Product_Observational xmlns="http://pds.nasa.gov/pds4/pds/v1">
  <Time_Coordinates><start_date_time>{time}</start_date_time></Time_Coordinates>
  <Mission_Area><Rover_Location>
    <Longitude>{lon}</Longitude><latitude>{lat}</latitude><altitude>-4.9</altitude>
  </Rover_Location></Mission_Area>
</Product_Observational>"""


def _moon_label(time: str, lat: float, lon: float) -> str:
    return f"""<Product_Observational>
  <start_date_time>{time}</start_date_time>
  <Mission_Area>
    <Lander_Location><latitude>-45.444600</latitude><longitude>177.599100</longitude></Lander_Location>
    <Rover_Location><latitude>{lat}</latitude><longitude>{lon}</longitude></Rover_Location>
    <Rover_LocationXYZ><x>-1.76</x><y>-12.69</y><z>-0.83</z></Rover_LocationXYZ>
  </Mission_Area>
</Product_Observational>"""


def _labels(root: Path, slug: str, labels: list[str]) -> None:
    folder = root / slug / "labels"
    folder.mkdir(parents=True)
    for i, raw in enumerate(labels):
        (folder / f"frame-{i:03}.2CL").write_text(raw)


class TestReadPosition:
    """What one label states."""

    def test_a_mars_label_states_the_rover_only(self):
        found = clpds_traverse.read_position(
            _mars_label("2021-06-03T09:01:52.514000Z", 25.083231, 109.908435)
        )
        assert found == {
            "time": "2021-06-03T09:01:52Z",
            "lat": 25.083231,
            "lon": 109.908435,
            "lander": None,
        }

    def test_a_lunar_label_states_the_lander_too(self):
        found = clpds_traverse.read_position(
            _moon_label("2019-01-04T04:15:18.011Z", -45.44502, 177.599017)
        )
        assert found is not None
        assert found["time"] == "2019-01-04T04:15:18Z"
        assert found["lander"] == (-45.4446, 177.5991)

    def test_a_west_longitude_is_read_as_east(self):
        found = clpds_traverse.read_position(
            _mars_label("2021-06-03T09:01:52Z", 25.0, -250.0)
        )
        assert found is not None
        assert found["lon"] == 110.0

    def test_a_label_with_no_rover_position_states_none(self):
        raw = (
            "<Product><start_date_time>2021-06-03T09:01:52Z</start_date_time></Product>"
        )
        assert clpds_traverse.read_position(raw) is None


class TestWaypoints:
    """One waypoint for each place, at the first label taken there."""

    def test_the_frames_of_one_stop_are_one_waypoint(self):
        positions = [
            {"time": "2021-06-03T09:03:27Z", "lat": 25.1, "lon": 109.9},
            {"time": "2021-06-03T09:01:52Z", "lat": 25.1, "lon": 109.9},
            {"time": "2021-06-05T10:51:15Z", "lat": 25.2, "lon": 109.9},
        ]
        assert clpds_traverse.waypoints(positions) == [
            ("2021-06-03T09:01:52Z", 25.1, 109.9),
            ("2021-06-05T10:51:15Z", 25.2, 109.9),
        ]

    def test_a_return_to_an_earlier_place_is_a_new_waypoint(self):
        positions = [
            {"time": "2021-06-03T09:01:52Z", "lat": 25.1, "lon": 109.9},
            {"time": "2021-06-04T09:01:52Z", "lat": 25.2, "lon": 109.9},
            {"time": "2021-06-05T09:01:52Z", "lat": 25.1, "lon": 109.9},
        ]
        assert [w[1] for w in clpds_traverse.waypoints(positions)] == [25.1, 25.2, 25.1]


class TestLandingPoint:
    """Where the frame of the labels puts the lander."""

    def test_the_stated_lander_position_is_used(self):
        positions = [
            {
                "time": "t1",
                "lat": -45.445,
                "lon": 177.599,
                "lander": (-45.4446, 177.5991),
            },
            {
                "time": "t2",
                "lat": -45.444,
                "lon": 177.598,
                "lander": (-45.4446, 177.5991),
            },
        ]
        assert clpds_traverse.landing_point(MOON_ROVER, positions) == (
            -45.4446,
            177.5991,
        )

    def test_labels_that_disagree_on_the_lander_are_refused(self):
        positions = [
            {"time": "t1", "lat": 0.0, "lon": 0.0, "lander": (-45.4446, 177.5991)},
            {"time": "t2", "lat": 0.0, "lon": 0.0, "lander": (-45.4447, 177.5991)},
        ]
        with pytest.raises(ValueError, match="disagree"):
            clpds_traverse.landing_point(MOON_ROVER, positions)

    def test_an_unstated_lander_is_placed_from_the_first_stop(self):
        positions = [
            {"time": "2021-06-05T10:51:15Z", "lat": 26.0, "lon": 110.0, "lander": None},
            {"time": "2021-06-03T09:01:52Z", "lat": 25.0, "lon": 110.0, "lander": None},
        ]
        lat, lon = clpds_traverse.landing_point(MARS_ROVER, positions)
        degree_m = 3389500.0 * 3.141592653589793 / 180
        assert (lat - 25.0) * degree_m == pytest.approx(4.3, abs=0.06)
        assert (lon - 110.0) * degree_m * 0.9063 == pytest.approx(-0.3, abs=0.06)

    def test_a_rover_with_no_way_to_find_the_lander_is_refused(self):
        positions = [{"time": "t1", "lat": 0.0, "lon": 0.0, "lander": None}]
        with pytest.raises(ValueError, match="nothing states"):
            clpds_traverse.landing_point(MOON_ROVER, positions)


class TestBuild:
    """Labels on disk become a traverse file."""

    def test_a_built_traverse_loads(self, tmp_path: Path):
        _labels(
            tmp_path / "sources",
            "yutu-2",
            [
                _moon_label("2019-01-10T21:11:29.000Z", -45.444298, 177.598821),
                _moon_label("2019-01-04T04:15:18.011Z", -45.44502, 177.599017),
                _moon_label("2019-01-04T04:16:40.000Z", -45.44502, 177.599017),
            ],
        )
        clpds_traverse.build(MOON_ROVER, tmp_path / "sources", tmp_path / "out")
        traverse = traverses.load_traverses(tmp_path / "out")[110784513]
        assert traverse.body_naif == 301
        assert (traverse.landing_lat_deg, traverse.landing_lon_deg) == (
            -45.4446,
            177.5991,
        )
        assert [(w.lat_deg, w.lon_deg) for w in traverse.waypoints] == [
            (-45.44502, 177.599017),
            (-45.444298, 177.598821),
        ]

    def test_labels_that_state_no_position_are_refused(self, tmp_path: Path):
        _labels(tmp_path, "zhurong", ["<Product/>"])
        with pytest.raises(ValueError, match="no label"):
            clpds_traverse.build(MARS_ROVER, tmp_path, tmp_path / "out")
