"""Tests for the manifest dispatch in `_build_metadata`.

Three input shapes (static / chunk-indexed / date-segmented) drive three
output shapes. Dispatch is on `SnapshotResult.chunk_years` (and on whether
`time` is None), not on label format — these tests pin that contract so a
future refactor can't silently regress to label-format heuristics.
"""

import pytest

from space_map_data.export.common import (
    SnapshotResult,
    ZoomSnapshots,
    _build_metadata,
)
from space_map_data.export.elements.format import (
    UNBOUNDED_END_JD,
    UNBOUNDED_START_JD,
)


def _result(
    *,
    time: str | None = None,
    num_parts: int = 1,
    chunk_years: float | None = None,
    validity_start_jd: float = UNBOUNDED_START_JD,
    validity_end_jd: float = UNBOUNDED_END_JD,
) -> SnapshotResult:
    return SnapshotResult(
        time=time,
        count=0,
        num_parts=num_parts,
        chunk_years=chunk_years,
        validity_start_jd=validity_start_jd,
        validity_end_jd=validity_end_jd,
    )


def _zoom(*results: SnapshotResult) -> ZoomSnapshots:
    return ZoomSnapshots(snapshots=list(results))


class TestStaticShape:
    """Single snapshot with ``time is None`` → ``{parts}`` only."""

    def test_emits_parts_only(self):
        meta = _build_metadata({"AMO": {0: _zoom(_result(num_parts=1))}})
        assert meta == {"zones": {"AMO": {"zooms": {"0": {"parts": 1}}}}}

    def test_carries_parts_count(self):
        meta = _build_metadata({"MBA": {0: _zoom(_result(num_parts=12))}})
        assert meta["zones"]["MBA"]["zooms"]["0"] == {"parts": 12}


class TestChunkIndexedShape:
    """Snapshots carrying ``chunk_years`` → ``{chunks, chunk_years, start_jd, parts}``."""

    def test_emits_chunk_indexed_keys(self):
        zoom = _zoom(
            _result(
                time="0",
                num_parts=1,
                chunk_years=0.5,
                validity_start_jd=2433282.5,
                validity_end_jd=2433465.125,
            ),
            _result(
                time="1",
                num_parts=1,
                chunk_years=0.5,
                validity_start_jd=2433465.125,
                validity_end_jd=2433647.75,
            ),
            _result(
                time="2",
                num_parts=1,
                chunk_years=0.5,
                validity_start_jd=2433647.75,
                validity_end_jd=2433830.375,
            ),
        )
        meta = _build_metadata({"moons": {0: zoom}})
        assert meta["zones"]["moons"]["zooms"]["0"] == {
            "chunks": 3,
            "chunk_years": 0.5,
            "start_jd": 2433282.5,
            "parts": 1,
        }

    def test_start_jd_uses_earliest_validity(self):
        # Insertion order must not affect the chosen start_jd; the manifest
        # is meant to be label-format-independent. Earliest validity wins.
        zoom = _zoom(
            _result(
                time="100",
                chunk_years=2.0,
                validity_start_jd=2400000.0,
                validity_end_jd=2400730.0,
            ),
            _result(
                time="0",
                chunk_years=2.0,
                validity_start_jd=2300000.0,
                validity_end_jd=2300730.0,
            ),
            _result(
                time="50",
                chunk_years=2.0,
                validity_start_jd=2350000.0,
                validity_end_jd=2350730.0,
            ),
        )
        meta = _build_metadata({"moons/pluto": {0: zoom}})
        assert meta["zones"]["moons/pluto"]["zooms"]["0"]["start_jd"] == 2300000.0
        assert meta["zones"]["moons/pluto"]["zooms"]["0"]["chunks"] == 3

    def test_rejects_mixed_chunk_years(self):
        zoom = _zoom(
            _result(time="0", chunk_years=0.5),
            _result(time="1", chunk_years=1.0),
        )
        with pytest.raises(ValueError, match="mixes chunk_years"):
            _build_metadata({"moons": {0: zoom}})

    def test_rejects_uneven_parts(self):
        zoom = _zoom(
            _result(time="0", num_parts=1, chunk_years=0.5),
            _result(time="1", num_parts=2, chunk_years=0.5),
        )
        with pytest.raises(ValueError, match="uneven parts"):
            _build_metadata({"moons": {0: zoom}})

    def test_rejects_static_mixed_with_timed(self):
        # A timed stream with a stray None-time entry is a producer bug; the
        # manifest dispatch can't pick a shape so we fail loudly.
        zoom = _zoom(
            _result(time=None, num_parts=1),
            _result(time="0", chunk_years=0.5),
        )
        with pytest.raises(ValueError, match="mixes timed snapshots"):
            _build_metadata({"moons": {0: zoom}})


class TestDateSegmentedShape:
    """ISO-date labels with no ``chunk_years`` → ``{start_date, end_date, parts}``."""

    def test_emits_date_range(self):
        zoom = _zoom(
            _result(time="2026-04-23", num_parts=1),
            _result(time="2026-04-24", num_parts=1),
            _result(time="2026-04-27", num_parts=1),
        )
        meta = _build_metadata({"earth": {0: zoom}})
        assert meta["zones"]["earth"]["zooms"]["0"] == {
            "start_date": "2026-04-23",
            "end_date": "2026-04-27",
            "parts": 1,
        }

    def test_picks_lex_min_max_dates(self):
        # ISO YYYY-MM-DD format makes lexicographic and chronological sort
        # agree; this test just pins the contract.
        zoom = _zoom(
            _result(time="2026-12-31"),
            _result(time="2026-01-01"),
            _result(time="2026-06-15"),
        )
        meta = _build_metadata({"earth": {0: zoom}})
        out = meta["zones"]["earth"]["zooms"]["0"]
        assert out["start_date"] == "2026-01-01"
        assert out["end_date"] == "2026-12-31"


class TestMixedZones:
    """All three shapes coexist in one manifest, picked per-zone independently."""

    def test_three_zones_three_shapes(self):
        meta = _build_metadata(
            {
                "AMO": {0: _zoom(_result(num_parts=1))},
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
                            chunk_years=0.5,
                            validity_start_jd=2433282.5,
                        ),
                    )
                },
            }
        )
        assert meta["zones"]["AMO"]["zooms"]["0"] == {"parts": 1}
        assert "start_date" in meta["zones"]["earth"]["zooms"]["0"]
        assert "chunk_years" in meta["zones"]["moons"]["zooms"]["0"]
