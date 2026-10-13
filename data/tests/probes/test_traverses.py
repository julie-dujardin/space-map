"""Rover traverses: the stored form and the shift onto the map's frame."""

import json
from pathlib import Path

import pytest

from space_map_data.probes import traverses
from space_map_data.probes.events import event_jd


def _write(root: Path, **overrides) -> Path:
    data = {
        "schema_version": 1,
        "probe_id": 113217538,
        "body_naif": 499,
        "source_url": "https://example.test/",
        "landing_point": {"lat_deg": 25.083, "lon_deg": 109.908},
        "waypoints": [
            {"time": "2021-06-03T09:01:52Z", "lat_deg": 25.083, "lon_deg": 109.908},
            {"time": "2021-06-05T10:51:15Z", "lat_deg": 25.082, "lon_deg": 109.909},
        ],
        **overrides,
    }
    path = root / f"{data['probe_id']}.json"
    path.write_text(json.dumps(data))
    return path


class TestLoad:
    """What `load_traverses` reads from a directory."""

    def test_a_traverse_is_keyed_by_its_probe(self, tmp_path: Path):
        _write(tmp_path)
        found = traverses.load_traverses(tmp_path)
        assert list(found) == [113217538]
        traverse = found[113217538]
        assert traverse.body_naif == 499
        assert [w.jd for w in traverse.waypoints] == [
            event_jd("2021-06-03T09:01:52Z"),
            event_jd("2021-06-05T10:51:15Z"),
        ]

    def test_a_missing_directory_holds_no_traverse(self, tmp_path: Path):
        assert traverses.load_traverses(tmp_path / "absent") == {}

    def test_waypoints_out_of_time_order_are_refused(self, tmp_path: Path):
        _write(
            tmp_path,
            waypoints=[
                {"time": "2021-06-05T10:51:15Z", "lat_deg": 25.0, "lon_deg": 109.0},
                {"time": "2021-06-03T09:01:52Z", "lat_deg": 25.0, "lon_deg": 109.0},
            ],
        )
        with pytest.raises(ValueError, match="time order"):
            traverses.load_traverses(tmp_path)

    def test_an_unknown_schema_is_refused(self, tmp_path: Path):
        _write(tmp_path, schema_version=2)
        with pytest.raises(ValueError, match="schema"):
            traverses.load_traverses(tmp_path)


class TestFromSite:
    """A waypoint keeps its offset from the landing point."""

    def test_the_landing_point_maps_to_the_site(self, tmp_path: Path):
        _write(tmp_path)
        traverse = traverses.load_traverses(tmp_path)[113217538]
        first, second = traverse.from_site(25.066, 109.925)
        assert (first.lat_deg, first.lon_deg) == pytest.approx((25.066, 109.925))
        assert second.lat_deg == pytest.approx(25.065)
        # The two latitudes differ by 0.017 degrees, so the stretch is small.
        assert second.lon_deg == pytest.approx(109.926, abs=1e-6)
        assert second.jd == traverse.waypoints[1].jd

    def test_a_degree_of_longitude_is_scaled_to_the_latitude_of_the_site(
        self, tmp_path: Path
    ):
        _write(
            tmp_path,
            landing_point={"lat_deg": 0.0, "lon_deg": 10.0},
            waypoints=[
                {"time": "2021-06-03T09:01:52Z", "lat_deg": 0.0, "lon_deg": 11.0}
            ],
        )
        traverse = traverses.load_traverses(tmp_path)[113217538]
        (moved,) = traverse.from_site(60.0, 10.0)
        assert moved.lon_deg == pytest.approx(12.0)


class TestWrite:
    """`write_traverse` writes a file that `load_traverses` reads."""

    def test_round_trip(self, tmp_path: Path):
        path = traverses.write_traverse(
            tmp_path,
            probe_id=110784513,
            body_naif=301,
            source_url="https://example.test/",
            landing_point=(-45.4446, 177.5991),
            waypoints=[("2019-01-04T04:15:18Z", -45.44502, 177.599017)],
        )
        assert path.name == "110784513.json"
        traverse = traverses.load_traverses(tmp_path)[110784513]
        assert (traverse.landing_lat_deg, traverse.landing_lon_deg) == (
            -45.4446,
            177.5991,
        )
        assert traverse.waypoints == (
            traverses.Waypoint(event_jd("2019-01-04T04:15:18Z"), -45.44502, 177.599017),
        )
