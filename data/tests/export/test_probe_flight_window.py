"""Tests for cutting a probe's kernel coverage to its launch and its end."""

import json
import math
from pathlib import Path

import pytest

from space_map_data.export.position.probes import classify, fit_cache
from space_map_data.probes import events
from space_map_data.probes.events import event_jd
from space_map_data.probes.zones import ZONES_BY_KEY
from space_map_data.utils.time import S_PER_DAY, jd_to_et, year_to_jd


def _et(iso: str) -> float:
    return jd_to_et(event_jd(iso))


@pytest.fixture
def events_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "events"
    root.mkdir()
    monkeypatch.setattr(events, "EVENTS_DIR", root)
    return root


def _write(root: Path, *probes: dict) -> None:
    for probe in probes:
        probe.setdefault("status", {"where": "impacted", "alive": False})
        probe.setdefault("description", "test probe")
    (root / "probes.json").write_text(
        json.dumps({"_meta": {"schema_version": "v3"}, "probes": list(probes)})
    )


def _crash(date: str) -> dict:
    return {"type": "landing", "date": date, "outcome": "destroyed_at_landing"}


class TestFlightWindows:
    def test_a_crash_ends_the_window(self, events_root: Path):
        """Deep Impact's impactor: its pre-encounter predict flies on for six
        months after it hit Tempel 1."""
        _write(
            events_root,
            {
                "probe_id": 1,
                "name": "Impactor",
                "events": [
                    {"type": "launch", "date": "2005-01-12T18:47:08Z"},
                    _crash("2005-07-04T05:52:00Z"),
                ],
            },
        )
        start, end = classify.flight_windows()[1]
        assert start == pytest.approx(_et("2005-01-12T18:47:08Z"), abs=1e-3)
        assert end == pytest.approx(_et("2005-07-04T05:52:00Z"), abs=1e-3)

    def test_a_controlled_landing_leaves_the_end_open(self, events_root: Path):
        """A lander's kernel goes on to place it on the surface."""
        _write(
            events_root,
            {
                "probe_id": 1,
                "name": "Lander",
                "events": [
                    {"type": "launch", "date": "2011-11-26T15:02:00Z"},
                    {"type": "atmospheric_entry", "date": "2012-08-06T05:10:45Z"},
                    {
                        "type": "landing",
                        "date": "2012-08-06T05:17:57Z",
                        "outcome": "controlled",
                    },
                ],
            },
        )
        start, end = classify.flight_windows()[1]
        assert start == pytest.approx(_et("2011-11-26T15:02:00Z"), abs=1e-3)
        assert end == math.inf

    def test_a_day_precision_end_is_where_the_crash_site_starts(
        self, events_root: Path
    ):
        """The landing phase starts at the day's midnight; flying on past it
        would hide the site."""
        _write(
            events_root,
            {"probe_id": 1, "name": "Orbiter", "events": [_crash("1967-10-31")]},
        )
        start, end = classify.flight_windows()[1]
        assert start == -math.inf
        assert end == pytest.approx(_et("1967-10-31"), abs=1e-3)

    def test_a_companion_crash_does_not_end_the_craft(self, events_root: Path):
        """LCROSS's record holds the Centaur's impact four minutes before its
        own."""
        _write(
            events_root,
            {
                "probe_id": 1,
                "name": "LCROSS",
                "events": [
                    _crash("2009-10-09T11:31:19Z"),
                    _crash("2009-10-09T11:35:36Z"),
                ],
            },
        )
        assert classify.flight_windows()[1][1] == pytest.approx(
            _et("2009-10-09T11:35:36Z"), abs=1e-3
        )

    def test_a_failed_launch_does_not_start_the_window(self, events_root: Path):
        _write(
            events_root,
            {
                "probe_id": 1,
                "name": "Orbiter",
                "events": [
                    {"type": "launch", "date": "1960-10-10", "failed": True},
                    {"type": "launch", "date": "1960-10-14"},
                ],
            },
        )
        assert classify.flight_windows()[1][0] == pytest.approx(
            _et("1960-10-14"), abs=1e-3
        )

    def test_a_probe_with_no_bounds_has_no_window(self, events_root: Path):
        _write(
            events_root,
            {
                "probe_id": 1,
                "name": "Orbiter",
                "events": [{"type": "orbit_insertion", "date": "2006-03-10"}],
            },
        )
        assert 1 not in classify.flight_windows()


class TestClipIntervals:
    def test_coverage_before_launch_is_cut(self):
        """BepiColombo's MPO kernel was planned for an April 2018 launch."""
        launch = _et("2018-10-20T01:45:28Z")
        intervals = [
            ("earth-moon", _et("2018-04-17T00:00:00Z"), _et("2018-11-01T00:00:00Z"))
        ]
        assert classify.clip_intervals(intervals, (launch, math.inf)) == [
            ("earth-moon", launch, _et("2018-11-01T00:00:00Z"))
        ]

    def test_an_interval_wholly_after_the_end_is_dropped(self):
        end = _et("2012-01-15T17:46:00Z")
        intervals = [
            ("earth-moon", _et("2011-11-09T00:00:00Z"), _et("2011-11-21T00:00:00Z")),
            ("mars", _et("2012-09-01T00:00:00Z"), _et("2013-02-14T00:00:00Z")),
        ]
        assert classify.clip_intervals(intervals, (-math.inf, end)) == intervals[:1]


class TestCutChunks:
    _START_JD = year_to_jd(1950)
    _ZONE = ZONES_BY_KEY["jupiter"]

    def _chunk_start(self, idx: int) -> float:
        return jd_to_et(self._START_JD) + idx * self._ZONE.chunk_days * S_PER_DAY

    def test_only_the_chunk_holding_the_end_is_cut(self):
        end = self._chunk_start(40) + 3600.0
        spans = [("jupiter", self._chunk_start(10), self._chunk_start(45))]
        assert classify._cut_chunks(spans, (-math.inf, end), self._START_JD) == {
            ("jupiter", 40)
        }

    def test_an_end_on_a_chunk_boundary_cuts_the_chunk_before(self):
        end = self._chunk_start(40)
        spans = [("jupiter", self._chunk_start(10), self._chunk_start(45))]
        assert classify._cut_chunks(spans, (-math.inf, end), self._START_JD) == {
            ("jupiter", 39)
        }

    def test_a_window_that_cuts_nothing_marks_nothing(self):
        spans = [("jupiter", self._chunk_start(10), self._chunk_start(45))]
        window = (self._chunk_start(5), self._chunk_start(50))
        assert classify._cut_chunks(spans, window, self._START_JD) == set()


def test_only_a_cut_chunk_carries_the_window_in_its_signature(tmp_path: Path):
    kernel = tmp_path / "k.bsp"
    kernel.write_bytes(b"k")

    def signature(window: tuple[float, float] | None, *, flying: bool) -> dict:
        return fit_cache.build_fit_signature(
            zone=ZONES_BY_KEY["jupiter"],
            kernels=[kernel],
            download_dir=tmp_path,
            candidates_hash="c",
            events_hash="e",
            has_flying=flying,
            has_landed=not flying,
            flight_window=window,
        )

    assert "flight_window" not in signature(None, flying=True)
    assert signature((-math.inf, 1.25e8), flying=True)["flight_window"] == [
        None,
        1.25e8,
    ]
    assert signature((1.0e8, math.inf), flying=False)["flight_window"] == [
        1.0e8,
        None,
    ]
