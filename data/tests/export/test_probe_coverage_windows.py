"""`_compute_probe_coverage` turns chunk contributions into coverage windows.

Chunk-sliced spans of one arc must come back as a single window, and a real
archive hole must survive as two.
"""

from space_map_data.export.position.probes.plan import (
    ChunkContribution,
    ProbeMeta,
    ProbePlan,
)
from space_map_data.export.position.probes.writer import (
    _compute_probe_coverage,
    _merge_spans,
)
from space_map_data.utils.time import jd_to_et


def _plan(probe_id: int, spans: list[tuple[float, float]]) -> ProbePlan:
    return ProbePlan(
        probe_id=probe_id,
        naif_id=-1,
        kernels=[],
        contributions=[
            ChunkContribution(
                zone_key="interplanetary",
                chunk_idx=i,
                c_start_et=jd_to_et(s),
                c_end_et=jd_to_et(e),
            )
            for i, (s, e) in enumerate(spans)
        ],
    )


def _meta(probe_id: int, obj_id: str) -> ProbeMeta:
    return ProbeMeta(
        probe_id=probe_id, obj_id=obj_id, object_type_ordinal=0, has_localized=False
    )


class TestMergeSpans:
    """Seams close, real holes stay open."""

    def test_touching_spans_merge(self):
        assert _merge_spans([(10.0, 20.0), (20.0, 30.0)]) == [(10.0, 30.0)]

    def test_sub_day_seam_merges(self):
        assert _merge_spans([(10.0, 20.0), (20.5, 30.0)]) == [(10.0, 30.0)]

    def test_multi_day_hole_survives(self):
        assert _merge_spans([(10.0, 20.0), (25.0, 30.0)]) == [
            (10.0, 20.0),
            (25.0, 30.0),
        ]

    def test_unsorted_and_nested_spans(self):
        assert _merge_spans([(25.0, 30.0), (10.0, 28.0)]) == [(10.0, 30.0)]


class TestComputeProbeCoverage:
    """Windows ship alongside the envelope that bounds them."""

    def test_contiguous_chunks_make_one_window(self):
        cov = _compute_probe_coverage(
            [_plan(7, [(2450000.0, 2450100.0), (2450100.0, 2450200.0)])],
            {7: _meta(7, "probe-7")},
        )
        assert cov["probe-7"]["windows"] == [(2450000.0, 2450200.0)]
        assert cov["probe-7"]["start_jd"] == 2450000.0
        assert cov["probe-7"]["end_jd"] == 2450200.0

    def test_archive_hole_makes_two_windows(self):
        cov = _compute_probe_coverage(
            [_plan(7, [(2450000.0, 2450100.0), (2451000.0, 2451100.0)])],
            {7: _meta(7, "probe-7")},
        )
        assert cov["probe-7"]["windows"] == [
            (2450000.0, 2450100.0),
            (2451000.0, 2451100.0),
        ]
        # The envelope still spans the hole, so a consumer reading only the
        # bounds behaves exactly as it did before windows existed.
        assert cov["probe-7"]["start_jd"] == 2450000.0
        assert cov["probe-7"]["end_jd"] == 2451100.0

    def test_probe_without_meta_is_dropped(self, caplog):
        cov = _compute_probe_coverage([_plan(9, [(2450000.0, 2450100.0)])], {})
        assert cov == {}
        assert "probe_id=9" in caplog.text
