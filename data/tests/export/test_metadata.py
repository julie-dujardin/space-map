"""Tests for the unified position manifest dispatch in `build_position_metadata`.

Three input shapes (static / chunk-indexed / date-segmented) drive three
output shapes plus the chebyshev-only `chunked` shape folded in from the
chebyshev manifest fragment. Dispatch is on `SnapshotResult.chunk_days`
(and on whether `time` is None), not on label format — these tests pin
that contract so a future refactor can't silently regress to label-format
heuristics.
"""

import pytest

from space_map_data.export.pipeline.manifest import (
    ZoomSnapshots,
    build_position_metadata,
)
from space_map_data.export.pipeline.zone import SnapshotResult
from space_map_data.export.position.format import (
    UNBOUNDED_END_JD,
    UNBOUNDED_START_JD,
)


def _result(
    *,
    time: str | None = None,
    num_parts: int = 1,
    chunk_days: float | None = None,
    validity_start_jd: float = UNBOUNDED_START_JD,
    validity_end_jd: float = UNBOUNDED_END_JD,
) -> SnapshotResult:
    return SnapshotResult(
        time=time,
        count=0,
        num_parts=num_parts,
        chunk_days=chunk_days,
        validity_start_jd=validity_start_jd,
        validity_end_jd=validity_end_jd,
    )


def _zoom(*results: SnapshotResult) -> ZoomSnapshots:
    return ZoomSnapshots(snapshots=list(results))


class TestStaticShape:
    """Single snapshot with ``time is None`` → ``{shape: parted, parts}``."""

    def test_emits_parted_shape(self):
        meta = build_position_metadata(
            {"small_bodies/AMO": {0: _zoom(_result(num_parts=1))}}, {}
        )
        assert meta == {
            "zones": {
                "small_bodies/AMO": {"zooms": {"0": {"shape": "parted", "parts": 1}}}
            }
        }

    def test_carries_parts_count(self):
        meta = build_position_metadata(
            {"small_bodies/MBA": {0: _zoom(_result(num_parts=12))}}, {}
        )
        assert meta["zones"]["small_bodies/MBA"]["zooms"]["0"] == {
            "shape": "parted",
            "parts": 12,
        }


class TestChunkIndexedShape:
    """Snapshots carrying ``chunk_days`` → chunked-parted with label=index."""

    def test_emits_chunk_indexed_keys(self):
        zoom = _zoom(
            _result(
                time="0",
                num_parts=1,
                chunk_days=0.5,
                validity_start_jd=2433282.5,
                validity_end_jd=2433465.125,
            ),
            _result(
                time="1",
                num_parts=1,
                chunk_days=0.5,
                validity_start_jd=2433465.125,
                validity_end_jd=2433647.75,
            ),
            _result(
                time="2",
                num_parts=1,
                chunk_days=0.5,
                validity_start_jd=2433647.75,
                validity_end_jd=2433830.375,
            ),
        )
        meta = build_position_metadata({"moons": {0: zoom}}, {})
        assert meta["zones"]["moons"]["zooms"]["0"] == {
            "shape": "chunked-parted",
            "label": "index",
            "chunks": 3,
            "chunk_days": 0.5,
            "start_jd": 2433282.5,
            "parts": 1,
        }

    def test_start_jd_uses_earliest_validity(self):
        # Insertion order must not affect the chosen start_jd; the manifest
        # is meant to be label-format-independent. Earliest validity wins.
        zoom = _zoom(
            _result(
                time="100",
                chunk_days=2.0,
                validity_start_jd=2400000.0,
                validity_end_jd=2400730.0,
            ),
            _result(
                time="0",
                chunk_days=2.0,
                validity_start_jd=2300000.0,
                validity_end_jd=2300730.0,
            ),
            _result(
                time="50",
                chunk_days=2.0,
                validity_start_jd=2350000.0,
                validity_end_jd=2350730.0,
            ),
        )
        meta = build_position_metadata({"moons/pluto": {0: zoom}}, {})
        assert meta["zones"]["moons/pluto"]["zooms"]["0"]["start_jd"] == 2300000.0
        assert meta["zones"]["moons/pluto"]["zooms"]["0"]["chunks"] == 3

    def test_rejects_mixed_chunk_days(self):
        zoom = _zoom(
            _result(time="0", chunk_days=0.5),
            _result(time="1", chunk_days=1.0),
        )
        with pytest.raises(ValueError, match="mixes chunk_days"):
            build_position_metadata({"moons": {0: zoom}}, {})

    def test_rejects_uneven_parts(self):
        zoom = _zoom(
            _result(time="0", num_parts=1, chunk_days=0.5),
            _result(time="1", num_parts=2, chunk_days=0.5),
        )
        with pytest.raises(ValueError, match="uneven parts"):
            build_position_metadata({"moons": {0: zoom}}, {})

    def test_rejects_static_mixed_with_timed(self):
        # A timed stream with a stray None-time entry is a producer bug; the
        # manifest dispatch can't pick a shape so we fail loudly.
        zoom = _zoom(
            _result(time=None, num_parts=1),
            _result(time="0", chunk_days=0.5),
        )
        with pytest.raises(ValueError, match="mixes timed snapshots"):
            build_position_metadata({"moons": {0: zoom}}, {})


class TestDateSegmentedShape:
    """ISO-date labels with no ``chunk_days`` → chunked-parted with label=date."""

    def test_emits_date_range(self):
        zoom = _zoom(
            _result(time="2026-04-23", num_parts=1),
            _result(time="2026-04-24", num_parts=1),
            _result(time="2026-04-27", num_parts=1),
        )
        meta = build_position_metadata({"earth": {0: zoom}}, {})
        assert meta["zones"]["earth"]["zooms"]["0"] == {
            "shape": "chunked-parted",
            "label": "date",
            "start_date": "2026-04-23",
            "end_date": "2026-04-27",
            "parts": 1,
            "parts_by_date": {
                "2026-04-23": 1,
                "2026-04-24": 1,
                "2026-04-27": 1,
            },
        }

    def test_allows_uneven_parts_per_date(self):
        # Date-segmented zones (earth) carry per-date part counts — historical
        # weekly snapshots hold the full decayed catalog (more parts) while
        # recent dailies are smaller. parts is the max bound.
        zoom = _zoom(
            _result(time="2024-01-01", num_parts=3),
            _result(time="2026-04-23", num_parts=2),
        )
        entry = build_position_metadata({"earth": {0: zoom}}, {})["zones"]["earth"][
            "zooms"
        ]["0"]
        assert entry["parts"] == 3
        assert entry["parts_by_date"] == {"2024-01-01": 3, "2026-04-23": 2}

    def test_picks_lex_min_max_dates(self):
        # ISO YYYY-MM-DD format makes lexicographic and chronological sort
        # agree; this test just pins the contract.
        zoom = _zoom(
            _result(time="2026-12-31"),
            _result(time="2026-01-01"),
            _result(time="2026-06-15"),
        )
        meta = build_position_metadata({"earth": {0: zoom}}, {})
        out = meta["zones"]["earth"]["zooms"]["0"]
        assert out["start_date"] == "2026-01-01"
        assert out["end_date"] == "2026-12-31"


class TestChebyshevShape:
    """Per-zone chebyshev fragment folds in as ``shape: chunked`` at zoom 0."""

    def test_emits_chunked_shape(self):
        meta = build_position_metadata(
            {},
            {
                "major": {
                    "chunks": 20,
                    "chunk_days": 5.0,
                    "start_jd": 2433282.5,
                    "end_jd": 2469807.5,
                }
            },
        )
        assert meta["zones"]["major"]["zooms"]["0"] == {
            "shape": "chunked",
            "chunks": 20,
            "chunk_days": 5.0,
            "start_jd": 2433282.5,
            "end_jd": 2469807.5,
        }

    def test_per_zone_cadence(self):
        """Different zones can ship different chunk_days (Saturn 0.125, Pluto 2)."""
        meta = build_position_metadata(
            {},
            {
                "moons/saturn": {
                    "chunks": 800,
                    "chunk_days": 0.125,
                    "start_jd": 2433282.5,
                    "end_jd": 2469807.5,
                },
                "moons/pluto": {
                    "chunks": 50,
                    "chunk_days": 2.0,
                    "start_jd": 2433282.5,
                    "end_jd": 2469807.5,
                },
            },
        )
        assert meta["zones"]["moons/saturn"]["zooms"]["0"]["chunk_days"] == 0.125
        assert meta["zones"]["moons/pluto"]["zooms"]["0"]["chunk_days"] == 2.0


class TestMixedZones:
    """All four shapes coexist in one manifest, picked per-zone+zoom independently."""

    def test_four_shapes(self):
        meta = build_position_metadata(
            {
                "small_bodies/AMO": {0: _zoom(_result(num_parts=1))},
                "earth": {
                    0: _zoom(
                        _result(time="2026-04-23"),
                        _result(time="2026-04-24"),
                    )
                },
                "moons": {
                    0: _zoom(
                        _result(
                            time="0",
                            chunk_days=0.5,
                            validity_start_jd=2433282.5,
                        ),
                    )
                },
            },
            {
                "major": {
                    "chunks": 20,
                    "chunk_days": 5.0,
                    "start_jd": 2433282.5,
                    "end_jd": 2469807.5,
                }
            },
        )
        assert meta["zones"]["small_bodies/AMO"]["zooms"]["0"]["shape"] == "parted"
        assert meta["zones"]["earth"]["zooms"]["0"]["shape"] == "chunked-parted"
        assert meta["zones"]["earth"]["zooms"]["0"]["label"] == "date"
        assert meta["zones"]["moons"]["zooms"]["0"]["shape"] == "chunked-parted"
        assert meta["zones"]["moons"]["zooms"]["0"]["label"] == "index"
        assert meta["zones"]["major"]["zooms"]["0"]["shape"] == "chunked"

    def test_chebyshev_collision_rejects(self):
        """Elements + chebyshev both at zoom 0 of the same zone is a producer bug."""
        with pytest.raises(ValueError, match="claim zoom 0"):
            build_position_metadata(
                {"major": {0: _zoom(_result(num_parts=1))}},
                {
                    "major": {
                        "chunks": 20,
                        "chunk_days": 5.0,
                        "start_jd": 0.0,
                        "end_jd": 1.0,
                    }
                },
            )


class TestProbeCoverage:
    """Per-probe coverage envelope folds in as `probe_coverage` alongside `zones`."""

    def test_emits_sorted_coverage_map(self):
        meta = build_position_metadata(
            {},
            {},
            probe_zones=None,
            probe_coverage={
                "probe-9999": {"start_jd": 2455000.0, "end_jd": 2456000.0},
                "probe-1111": {"start_jd": 2450000.0, "end_jd": 2451000.0},
            },
        )
        assert list(meta["probe_coverage"].keys()) == ["probe-1111", "probe-9999"]
        assert meta["probe_coverage"]["probe-1111"] == {
            "start_jd": 2450000.0,
            "end_jd": 2451000.0,
        }

    def test_omitted_when_empty(self):
        meta = build_position_metadata({}, {}, probe_zones=None, probe_coverage={})
        assert "probe_coverage" not in meta

    def test_omitted_when_none(self):
        meta = build_position_metadata({}, {})
        assert "probe_coverage" not in meta
