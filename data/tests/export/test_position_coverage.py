"""Tests for space_map_data.export.position.coverage.

The windows are checked against a model of the frontend that knows only the
scenario: which snapshot it loads for a clock date, and the gates on a row.
"""

import bisect
import gzip
import logging
import math
import struct
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from space_map_data.constants.earth_sats.satcat import OrbitCenter
from space_map_data.constants.providers import ID_TYPES
from space_map_data.export.manual import _global
from space_map_data.export.objects.compact import CompactMap
from space_map_data.export.pipeline.orchestrator import _inject_coverage
from space_map_data.export.position.coverage import (
    _label_jds,
    _snapshot_slices,
    build_coverage,
    check_snapshot_windows,
    load_hosts,
    stamp_coverage,
    stamp_hosts,
)
from space_map_data.export.position.elements.writer import (
    write_elements,
    write_parabolic_elements,
    write_sgp4_elements,
)
from space_map_data.export.position.format import (
    ID_TYPE_ORDINAL,
    OBJECT_TYPE_ORDINAL,
    pack_body_header,
    pack_chebyshev_header,
)
from space_map_data.export.position.reader import (
    read_chebyshev_file,
    read_elements_file,
)
from space_map_data.models.object import Object, ObjectType, OrbitalSource, Satcat
from space_map_data.models.object.sbdb import SBDB
from space_map_data.utils.convert import date_to_julian
from space_map_data.utils.time import J2000_JD
from tests.conftest import make_object

_NAIF = ID_TYPE_ORDINAL[ID_TYPES.NAIF]
_SPKID = ID_TYPE_ORDINAL[ID_TYPES.SPKID]


def _jd(iso: str) -> float:
    jd = date_to_julian(date.fromisoformat(iso))
    assert jd is not None
    return jd


def _satellite(norad: int, launch: str | None = None) -> Object:
    obj = make_object(
        id=f"norad_satcat-{norad}",
        naif_id=None,
        norad_cat_id=norad,
        object_type=ObjectType.spacecraft,
        parent_id="naif-399",
        orbital_source=OrbitalSource.spacetrack,
        daily_kepler={
            "epoch_jd": 2451550.0,
            "a": 6795.0,
            "e": 0.0003,
            "i": 51.6,
            "om": 68.6,
            "w": 343.4,
            "ma": 78.0,
            "n": 15.5,
            "BSTAR": 2.9e-4,
            "MEAN_MOTION_DOT": 1.6e-4,
            "MEAN_MOTION_DDOT": 0.0,
            "ELEMENT_SET_NO": 1,
            "REV_AT_EPOCH": 1,
        },
    )
    if launch is not None:
        obj.satcat_norad_cat_id = norad
        obj.satcat = Satcat(NORAD_CAT_ID=norad, launch_date=launch)
    return obj


def _small_body(spkid: int, first_obs: str | None = None, **sbdb) -> Object:
    obj = make_object(
        id=f"spkid-{spkid}",
        object_type=ObjectType.asteroid,
        spkid=spkid,
        orbital_source=OrbitalSource.sbdb,
    )
    elements = dict(
        epoch=2460000.5, a=2.0, e=0.1, i=5.0, om=10.0, w=20.0, ma=30.0, n=0.5
    )
    obj.sbdb = SBDB(
        spkid=str(spkid),
        object_id=obj.id,
        first_obs=first_obs,
        **{**elements, **sbdb},
    )
    return obj


def _windows(out_dir: Path, zones: dict, decay: dict[int, float] | None = None) -> dict:
    return dict(build_coverage(out_dir, zones, decay or {}).objects())


# The snapshot scenario. Labels are a week apart, with one week missing and
# one label a single day after another, so a midpoint falls on a half day.
_LABELS = ["2000-01-03", "2000-01-10", "2000-01-17", "2000-01-31", "2000-02-01"]
_MEMBERS = {
    "2000-01-03": {1, 2, 3, 4, 5, 6, 7},
    "2000-01-10": {1, 2, 4, 5, 6},
    "2000-01-17": {1, 3, 4, 6},
    "2000-01-31": {1, 6, 9},
    "2000-02-01": {1, 6, 8},
}
_LAUNCH = {4: "2000-01-05", 5: "2000-01-08", 7: "2000-01-07"}
_DECAY = {6: _jd("2000-01-12")}


def _validity(label: str) -> tuple[float, float]:
    return _jd(label) - 14.0, _jd(label) + 21.0


def _write_snapshots(out_dir: Path) -> dict:
    """Write the scenario as an `earth` zone and return its manifest entry."""
    for label, members in _MEMBERS.items():
        path = out_dir / "position" / "earth" / label / "0.bin.gz"
        path.parent.mkdir(parents=True)
        start_jd, end_jd = _validity(label)
        write_sgp4_elements(
            [_satellite(norad, _LAUNCH.get(norad)) for norad in sorted(members)],
            path,
            OrbitalSource.spacetrack,
            has_localized={},
            start_jd=start_jd,
            end_jd=end_jd,
        )
    return {
        "earth": {
            "shape": "chunked-parted",
            "label": "date",
            "start_date": _LABELS[0],
            "end_date": _LABELS[-1],
            "parts": 1,
            "parts_by_date": {label: 1 for label in _LABELS},
        }
    }


def _frontend_snapshot(jd: float) -> str:
    """The label `snapshotDate` picks: nearest, the earlier one on a tie."""
    jds = [_jd(label) for label in _LABELS]
    if jd <= jds[0]:
        return _LABELS[0]
    if jd >= jds[-1]:
        return _LABELS[-1]
    after = bisect.bisect_left(jds, jd)
    earlier = jd - jds[after - 1] <= jds[after] - jd
    return _LABELS[after - 1 if earlier else after]


def _frontend_places(norad: int, jd: float) -> bool:
    """Whether the frontend draws the satellite at a clock date."""
    label = _frontend_snapshot(jd)
    if norad not in _MEMBERS[label]:
        return False
    start_jd, end_jd = _validity(label)
    if not start_jd <= jd <= end_jd:
        return False
    launch = _LAUNCH.get(norad)
    # The writer drops the gate of a row launched before its file starts.
    return launch is None or _jd(launch) <= start_jd or jd >= _jd(launch)


def _inside(windows: list, jd: float) -> bool:
    return any(
        (start is None or start < jd) and (end is None or jd < end)
        for start, end in windows
    )


class TestSnapshotWindows:
    """A date-labelled zone gives each object the clock dates for which the
    nearest-label rule loads a snapshot that holds it."""

    @pytest.fixture
    def windows(self, tmp_path) -> dict:
        return _windows(tmp_path, _write_snapshots(tmp_path), _DECAY)

    def test_matches_the_frontend_on_a_grid_of_clock_dates(self, windows):
        # Satellite 6 is left out: the frontend model does not know re-entry.
        first, last = _jd(_LABELS[0]), _jd(_LABELS[-1])
        for norad in (1, 2, 3, 4, 5, 7, 8, 9):
            got = windows.get(f"norad_satcat-{norad}", [])
            for jd in np.arange(first - 20.0, last + 10.0, 0.173).tolist():
                assert _inside(got, jd) == _frontend_places(norad, jd), (norad, jd)

    def test_run_from_the_first_label_to_an_open_end(self, windows):
        # In every snapshot: one run, which the last snapshot leaves open.
        assert windows["norad_satcat-1"] == [[_jd("2000-01-03") - 14.0, None]]

    def test_run_stops_at_the_midpoint_after_its_last_snapshot(self, windows):
        assert windows["norad_satcat-2"] == [
            [_jd("2000-01-03") - 14.0, (_jd("2000-01-10") + _jd("2000-01-17")) / 2]
        ]

    def test_hole_splits_the_run(self, windows):
        assert windows["norad_satcat-3"] == [
            [_jd("2000-01-03") - 14.0, _jd("2000-01-06") + 0.5],
            [_jd("2000-01-13") + 0.5, _jd("2000-01-24")],
        ]

    def test_launch_after_the_first_label_starts_the_window(self, windows):
        assert windows["norad_satcat-4"][0][0] == _jd("2000-01-05")

    def test_launch_after_the_first_cell_starts_in_the_next_snapshot(self, windows):
        assert windows["norad_satcat-5"] == [
            [_jd("2000-01-08"), (_jd("2000-01-10") + _jd("2000-01-17")) / 2]
        ]

    def test_launch_after_the_only_cell_gives_no_window(self, windows):
        assert "norad_satcat-7" not in windows

    def test_decay_clips_the_window(self, windows):
        # In every snapshot, the last one too, but re-entered on 12 January.
        assert windows["norad_satcat-6"] == [[_jd("2000-01-03") - 14.0, _DECAY[6]]]

    def test_last_snapshot_alone_gives_an_open_window(self, windows):
        assert windows["norad_satcat-8"] == [[_jd("2000-01-31") + 0.5, None]]

    def test_tie_goes_to_the_earlier_snapshot(self, windows):
        # 31 January noon is as far from one label as from the other.
        tie = _jd("2000-01-31") + 0.5
        assert _frontend_snapshot(tie) == "2000-01-31"
        assert windows["norad_satcat-9"] == [[_jd("2000-01-24"), tie]]
        assert _frontend_places(9, tie - 1e-3)
        assert not _frontend_places(9, tie + 1e-3)

    def test_decay_past_the_last_validity_leaves_the_end_open(self, tmp_path):
        zones = _write_snapshots(tmp_path)
        late = {1: _jd("2000-02-01") + 30.0}
        assert _windows(tmp_path, zones, late)["norad_satcat-1"][0][1] is None

    def test_file_validity_cuts_the_cell(self, tmp_path):
        zones = _write_snapshots(tmp_path)
        label = "2000-01-17"
        write_sgp4_elements(
            [_satellite(20)],
            tmp_path / "position" / "earth" / label / "1.bin.gz",
            OrbitalSource.spacetrack,
            has_localized={},
            start_jd=_jd(label) - 1.0,
            end_jd=_jd(label) + 2.0,
        )
        zones["earth"]["parts_by_date"][label] = 2
        windows = _windows(tmp_path, zones)
        assert windows["norad_satcat-20"] == [[_jd(label) - 1.0, _jd(label) + 2.0]]

    def test_object_in_two_parts_keeps_the_dates_both_rows_pass(self, tmp_path, caplog):
        zones = _write_snapshots(tmp_path)
        label = "2000-01-17"
        write_sgp4_elements(
            [_satellite(3)],
            tmp_path / "position" / "earth" / label / "1.bin.gz",
            OrbitalSource.spacetrack,
            has_localized={},
            start_jd=_jd(label) - 1.0,
            end_jd=_jd(label) + 2.0,
        )
        zones["earth"]["parts_by_date"][label] = 2
        with caplog.at_level(logging.WARNING):
            windows = _windows(tmp_path, zones)
        assert windows["norad_satcat-3"][1] == [_jd(label) - 1.0, _jd(label) + 2.0]
        assert "repeat an object" in caplog.text


class TestSnapshotSelfCheck:
    """The self-check reads the files again and tests each window edge."""

    def _layer(self, tmp_path):
        zones = _write_snapshots(tmp_path)
        slices = _snapshot_slices(
            tmp_path / "position" / "earth", zones["earth"]["parts_by_date"], _LABELS
        )
        index = build_coverage(tmp_path, zones, _DECAY)
        return slices, (index.keys, index.starts, index.ends)

    def test_built_windows_pass(self, tmp_path):
        slices, rows = self._layer(tmp_path)
        assert check_snapshot_windows("earth", _label_jds(_LABELS), slices, rows) == 0

    def test_window_into_a_snapshot_without_the_object_fails(self, tmp_path, caplog):
        slices, (keys, starts, ends) = self._layer(tmp_path)
        # Satellite 2 is not in the 17 January snapshot.
        row = int(np.flatnonzero((keys & 0xFFFFFFFF) == 2)[0])
        ends = ends.copy()
        ends[row] = _jd("2000-01-17") + 1.0
        with caplog.at_level(logging.ERROR):
            failed = check_snapshot_windows(
                "earth", _label_jds(_LABELS), slices, (keys, starts, ends)
            )
        assert failed == 1
        assert "norad_satcat-2" in caplog.text


class TestElementWindows:
    """A row of an elements zone is placed from its gate to the end of the
    file's validity window."""

    def _zone(self, out_dir: Path, objects: list[Object]) -> dict:
        path = out_dir / "position" / "small_bodies" / "APO" / "0" / "0.bin.gz"
        path.parent.mkdir(parents=True)
        write_elements(objects, path, OrbitalSource.sbdb, has_localized={})
        return {"small_bodies/APO": {"zooms": {"0": {"shape": "parted", "parts": 1}}}}

    def test_discovery_gate_starts_an_unbounded_window(self, tmp_path):
        zones = self._zone(
            tmp_path, [_small_body(2000001, "2001-01-01"), _small_body(2000002)]
        )
        assert _windows(tmp_path, zones) == {
            "spkid-2000001": [[_jd("2001-01-01"), None]],
            "spkid-2000002": [[None, None]],
        }

    def test_row_with_a_missing_element_gets_no_window(self, tmp_path):
        broken = _small_body(2000003, ma=None, condition_code="9")
        zones = self._zone(tmp_path, [broken, _small_body(2000002)])
        assert list(_windows(tmp_path, zones)) == ["spkid-2000002"]

    def test_parabolic_row(self, tmp_path):
        comet = _small_body(1000001, "1996-01-30", q=0.9, tp=2450000.5)
        path = tmp_path / "position" / "small_bodies" / "PAR" / "0" / "0.bin.gz"
        path.parent.mkdir(parents=True)
        write_parabolic_elements([comet], path, OrbitalSource.sbdb, has_localized={})
        zones = {"small_bodies/PAR": {"zooms": {"0": {"shape": "parted", "parts": 1}}}}
        assert _windows(tmp_path, zones) == {
            "spkid-1000001": [[_jd("1996-01-30"), None]]
        }

    def test_chunked_layer_joins_its_chunks(self, tmp_path):
        # Two 10-day chunks; the second moon is found 3 days into the first.
        old = make_object(id="naif-501", naif_id=501, object_type=ObjectType.moon)
        new = make_object(id="naif-558", naif_id=558, object_type=ObjectType.moon)
        new.discovery_year = 2000
        gate = _jd("2000-01-01")
        for chunk in range(2):
            path = tmp_path / "position" / "moons" / str(chunk) / "0.bin.gz"
            path.parent.mkdir(parents=True)
            write_elements(
                [old, new],
                path,
                OrbitalSource.spice,
                has_localized={},
                start_jd=gate - 3.0 + 10.0 * chunk,
                end_jd=gate + 7.0 + 10.0 * chunk,
            )
        zones = {
            "moons": {
                "shape": "chunked-parted",
                "label": "index",
                "chunks": 2,
                "chunk_days": 10.0,
                "start_jd": gate - 3.0,
                "parts": 1,
            }
        }
        assert _windows(tmp_path, zones) == {
            "naif-501": [[gate - 3.0, gate + 17.0]],
            "naif-558": [[gate, gate + 17.0]],
        }


def _chebyshev_file(
    path: Path,
    bodies: list[tuple[int, int, float, list[tuple[float, float]]]],
) -> None:
    """Write a chebyshev file of `(id_type, id, visible_from_days, segments)`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = [pack_chebyshev_header(0.0, 0.0, len(bodies))]
    for id_type, value, visible_from_days, segments in bodies:
        buf.append(
            pack_body_header(
                naif_id=value,
                parent_id=999,
                obj_id_value=value,
                radius_km=1.0,
                coeffs_per_axis=2,
                id_type_ordinal=id_type,
                has_localized=False,
                object_type_ordinal=OBJECT_TYPE_ORDINAL[ObjectType.moon],
                segment_count=len(segments),
                visible_from_days=visible_from_days,
            )
        )
        for start, end in segments:
            buf.append(struct.pack("<dd", start, end) + struct.pack("<6f", *[0.0] * 6))
    path.write_bytes(gzip.compress(b"".join(buf)))


class TestChebyshevWindows:
    """A chebyshev body is placed where the segments of the chunk the
    frontend loads cover the clock, after its discovery gate."""

    START = J2000_JD + 1000.5

    def _zone(self, out_dir: Path, chunks: list[list]) -> dict:
        for chunk, bodies in enumerate(chunks):
            _chebyshev_file(
                out_dir / "position" / "moons" / "pluto" / f"{chunk}.bin.gz", bodies
            )
        return {
            "moons/pluto": {
                "shape": "chunked",
                "chunks": len(chunks),
                "chunk_days": 10.0,
                "start_jd": self.START,
                "end_jd": self.START + 10.0 * len(chunks),
            }
        }

    def test_reads_back_the_segment_spans(self, tmp_path):
        s = self.START
        path = tmp_path / "0.bin.gz"
        _chebyshev_file(path, [(_NAIF, 901, math.nan, [(s, s + 5), (s + 5, s + 10)])])
        (body,) = read_chebyshev_file(path).bodies
        assert (body.id_type, body.obj_id_value) == (_NAIF, 901)
        assert math.isnan(body.visible_from_days)
        assert body.starts.tolist() == [s, s + 5]
        assert body.ends.tolist() == [s + 5, s + 10]

    def test_full_span_gate_hole_and_late_start(self, tmp_path):
        s = self.START
        whole = [(s, s + 5), (s + 5, s + 10)]
        zones = self._zone(
            tmp_path,
            [
                [
                    (_NAIF, 901, math.nan, whole),
                    (_NAIF, 904, s + 3 - J2000_JD, whole),
                    (_NAIF, 905, math.nan, [(s, s + 2), (s + 4, s + 10)]),
                ],
                [
                    (_NAIF, 901, math.nan, [(s + 10, s + 20)]),
                    (_NAIF, 904, math.nan, [(s + 10, s + 20)]),
                    (_NAIF, 905, math.nan, [(s + 10, s + 20)]),
                    (_NAIF, 906, math.nan, [(s + 10, s + 21)]),
                ],
            ],
        )
        assert _windows(tmp_path, zones) == {
            "naif-901": [[s, s + 20]],
            "naif-904": [[s + 3, s + 20]],
            "naif-905": [[s, s + 2], [s + 4, s + 20]],
            # The last chunk also serves the dates past the grid.
            "naif-906": [[s + 10, s + 21]],
        }

    def test_segment_of_another_chunk_does_not_count(self, tmp_path):
        # A segment that runs into the next chunk is cut at the chunk bound:
        # the frontend loads the next file there, and this body is not in it.
        s = self.START
        zones = self._zone(
            tmp_path,
            [
                [(_NAIF, 901, math.nan, [(s, s + 12)])],
                [(_NAIF, 902, math.nan, [(s + 10, s + 20)])],
            ],
        )
        assert _windows(tmp_path, zones)["naif-901"] == [[s, s + 10]]

    def test_element_row_carries_a_body_outside_its_segments(self, tmp_path):
        s = self.START
        _chebyshev_file(
            tmp_path / "position" / "major_asteroids" / "0.bin.gz",
            [(_SPKID, 2000001, math.nan, [(s, s + 5)])],
        )
        path = tmp_path / "position" / "small_bodies" / "APO" / "0" / "0.bin.gz"
        path.parent.mkdir(parents=True)
        write_elements(
            [_small_body(2000001, "1990-01-01")],
            path,
            OrbitalSource.sbdb,
            has_localized={},
        )
        zones = {
            "major_asteroids": {
                "shape": "chunked",
                "chunks": 1,
                "chunk_days": 10.0,
                "start_jd": s,
                "end_jd": s + 10.0,
            },
            "small_bodies/APO": {"zooms": {"0": {"shape": "parted", "parts": 1}}},
        }
        assert _windows(tmp_path, zones) == {
            "spkid-2000001": [[_jd("1990-01-01"), None]]
        }


class TestReadElementsFile:
    """The reader finds the ids, gates and missing elements of each sub-format."""

    def test_sgp4_ids_and_launch_gate(self, tmp_path):
        path = tmp_path / "sgp4.bin.gz"
        write_sgp4_elements(
            [_satellite(5), _satellite(25544, "1998-11-20")],
            path,
            OrbitalSource.spacetrack,
            has_localized={},
            start_jd=2451000.0,
            end_jd=2451035.0,
        )
        file = read_elements_file(path)
        assert (file.start_jd, file.end_jd) == (2451000.0, 2451035.0)
        assert file.id_type == ID_TYPE_ORDINAL[ID_TYPES.NORAD_SATCAT]
        assert file.ids.tolist() == [5, 25544]
        assert math.isnan(file.visible_from_days[0])
        assert J2000_JD + float(file.visible_from_days[1]) == _jd("1998-11-20")
        assert file.placeable.tolist() == [True, True]

    def test_empty_file(self, tmp_path):
        path = tmp_path / "empty.bin.gz"
        write_elements([], path, OrbitalSource.sbdb, has_localized={})
        file = read_elements_file(path)
        assert len(file.ids) == 0
        assert len(file.visible_from_days) == 0


class TestStampCoverage:
    """The windows land on the bundle entry, with null for an open bound."""

    def test_writes_the_block_and_keeps_the_entry_compact(self, tmp_path):
        zones = _write_snapshots(tmp_path)
        global_data = CompactMap()
        global_data["norad_satcat-8"] = {"id": "norad_satcat-8"}
        stamp_coverage(global_data, build_coverage(tmp_path, zones, {}))
        assert isinstance(global_data._data["norad_satcat-8"], bytes)
        assert global_data["norad_satcat-8"] == {
            "id": "norad_satcat-8",
            "coverage": {"windows": [[_jd("2000-01-31") + 0.5, None]]},
        }

    def test_object_without_a_bundle_entry_warns(self, tmp_path, caplog):
        zones = _write_snapshots(tmp_path)
        global_data: dict[str, dict] = {}
        with caplog.at_level(logging.WARNING):
            stamp_coverage(global_data, build_coverage(tmp_path, zones, {}))
        assert global_data == {}
        assert "no bundle entry" in caplog.text


class TestHosts:
    """An object the map cannot place names what it sits at or orbits."""

    def _catalogue(self, session) -> None:
        def sat(norad: int, **satcat) -> None:
            session.add(Satcat(NORAD_CAT_ID=norad, **satcat))
            session.add(
                Object(
                    id=f"norad_satcat-{norad}",
                    object_type=ObjectType.spacecraft,
                    norad_cat_id=norad,
                    satcat_norad_cat_id=norad,
                    parent_id="naif-399",
                )
            )

        sat(2, orbit_center=OrbitCenter.EARTH)
        sat(26400, orbit_center=OrbitCenter.DOCKED, orbit_center_docked_to=25544)
        sat(30, orbit_center=OrbitCenter.EARTH_L2)
        session.add(
            Object(
                id="spkid-220136108",
                object_type=ObjectType.moon,
                parent_id="spkid-20136108",
                orbital_source=OrbitalSource.sbdb_moon,
            )
        )
        session.commit()

    def test_moon_docked_craft_and_centre_body(self, session):
        self._catalogue(session)
        assert load_hosts(session) == {
            "norad_satcat-2": "naif-399",
            "norad_satcat-26400": "norad_satcat-25544",
            "spkid-220136108": "spkid-20136108",
        }

    def test_host_only_where_there_is_no_coverage(self):
        global_data = {
            "naif-399": {"id": "naif-399"},
            "norad_satcat-2": {"id": "norad_satcat-2"},
            "norad_satcat-5": {"id": "norad_satcat-5", "coverage": {"windows": []}},
        }
        stamp_hosts(
            global_data, {"norad_satcat-2": "naif-399", "norad_satcat-5": "naif-399"}
        )
        assert global_data["norad_satcat-2"]["host_id"] == "naif-399"
        assert "host_id" not in global_data["norad_satcat-5"]

    def test_host_without_a_bundle_entry_warns(self, caplog):
        global_data = {"norad_satcat-26400": {"id": "norad_satcat-26400"}}
        with caplog.at_level(logging.WARNING):
            stamp_hosts(global_data, {"norad_satcat-26400": "norad_satcat-25544"})
        assert "host_id" not in global_data["norad_satcat-26400"]
        assert "norad_satcat-25544" in caplog.text

    def test_export_step_stamps_coverage_then_hosts(self, engine, session, tmp_path):
        self._catalogue(session)
        session.add(Satcat(NORAD_CAT_ID=6, decay_date="2000-01-12"))
        session.commit()
        zones = _write_snapshots(tmp_path)
        global_data: dict[str, dict] = {
            oid: {"id": oid}
            for oid in (
                "naif-399",
                "norad_satcat-2",
                "norad_satcat-6",
                "norad_satcat-7",
            )
        }
        _inject_coverage(engine, tmp_path, global_data, zones)
        # Satellite 2 is in two snapshots, so it is placed and names no host.
        assert "host_id" not in global_data["norad_satcat-2"]
        assert global_data["norad_satcat-6"]["coverage"]["windows"][0][1] == _DECAY[6]
        # Satellite 7 is in a file but its launch gate hides it for good.
        assert "coverage" not in global_data["norad_satcat-7"]


class TestManualObjectCoverage:
    """A manual object is placed from its orbit block, at any date."""

    def _entry(self, **elements) -> dict:
        orbit = dict(epoch=2451545.0, a=1.0, e=0.1, i=1.0, om=2.0, w=3.0, ma=4.0, n=1.0)
        return {
            "id": "extra-1",
            "parent_id": "naif-10",
            "elements": {**orbit, **elements},
        }

    def test_complete_orbit_is_always_covered(self):
        assert _global(self._entry(), "Teapot")["coverage"] == {
            "windows": [[None, None]]
        }

    def test_incomplete_orbit_gets_no_coverage(self, caplog):
        with caplog.at_level(logging.WARNING):
            data = _global(self._entry(ma=None), "Teapot")
        assert "coverage" not in data
        assert "extra-1" in caplog.text
