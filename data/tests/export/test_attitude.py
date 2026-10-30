"""Attitude stack unit tests: wire format, quaternions, keyframe extraction,
baseline spin fit — all synthetic, no kernels needed. The cached-CK
end-to-end smoke lives in `scripts/probe_orientation_smoke.py`.
"""

import math
import struct

import numpy as np

from space_map_data.export.position.probes.attitude.baseline import (
    fit_spin_baseline,
)
from space_map_data.export.position.probes.attitude.format import (
    COMPONENT_SCALE,
    HEADER_SIZE,
    KEYFRAME_SIZE,
    MAGIC,
    VERSION,
    dequantise_component,
    pack_header,
    pack_keyframe,
    quantise_component,
    unpack_header,
    unpack_keyframe,
)
from space_map_data.export.position.probes.attitude.keyframes import (
    extract_keyframes,
)
from space_map_data.export.position.probes.attitude.quaternion import (
    angle_between,
    q_conj,
    q_mul,
    slerp,
)

# ── Wire format ──────────────────────────────────────────────────────────


def test_header_roundtrip() -> None:
    buf = pack_header(start_jd=2454046.5)
    assert len(buf) == HEADER_SIZE
    assert buf[:4] == MAGIC
    version, start_jd = unpack_header(buf)
    assert version == VERSION
    assert start_jd == 2454046.5


def test_header_rejects_wrong_magic() -> None:
    bad = b"NOPE" + struct.pack("<HBBd", VERSION, 0, 0, 0.0)
    try:
        unpack_header(bad)
    except ValueError:
        return
    raise AssertionError("unpack_header should reject foreign magic")


def test_keyframe_roundtrip_extreme_values() -> None:
    # Max int16 components + sub-second dt: float32 must keep spacing integers drop.
    kf = pack_keyframe(
        dt_seconds=0.125,
        idx=3,
        a=COMPONENT_SCALE,
        b=-COMPONENT_SCALE,
        c=0,
    )
    assert len(kf) == KEYFRAME_SIZE
    dt, idx, a, b, c = unpack_keyframe(kf, 0)
    assert dt == 0.125  # exact in float32
    assert idx == 3
    assert (a, b, c) == (COMPONENT_SCALE, -COMPONENT_SCALE, 0)


def test_component_quantisation_clamps() -> None:
    assert quantise_component(2.0) == COMPONENT_SCALE
    assert quantise_component(-2.0) == -COMPONENT_SCALE
    assert quantise_component(0.0) == 0
    # Round-trip should be within one quantisation step.
    for v in (-0.999, -0.5, 0.0, 0.25, 0.999):
        recovered = dequantise_component(quantise_component(v))
        assert abs(recovered - v) <= 1.0 / COMPONENT_SCALE + 1e-9


# ── Quaternion utilities ─────────────────────────────────────────────────


_IDENTITY = np.array([1.0, 0.0, 0.0, 0.0])


def test_q_mul_identity() -> None:
    q = np.array([math.cos(0.3), math.sin(0.3), 0.0, 0.0])
    out = q_mul(_IDENTITY, q)
    assert np.allclose(out, q)


def test_q_conj_inverse() -> None:
    q = np.array([math.cos(0.25), 0.5, 0.5, 0.5 * math.sqrt(2.0)])
    q /= np.linalg.norm(q)
    out = q_mul(q, q_conj(q))
    assert np.allclose(out, _IDENTITY, atol=1e-12)


def test_slerp_endpoints() -> None:
    q0 = _IDENTITY
    q1 = np.array([math.cos(0.5), math.sin(0.5), 0.0, 0.0])
    assert np.allclose(slerp(q0, q1, 0.0), q0)
    assert np.allclose(slerp(q0, q1, 1.0), q1)


def test_angle_between_identical() -> None:
    assert angle_between(_IDENTITY, _IDENTITY) == 0.0


# ── Adaptive keyframes ───────────────────────────────────────────────────


def test_extract_keyframes_constant_attitude() -> None:
    """A truly stationary attitude needs exactly 2 keyframes (start + end)."""
    n = 1000
    quats = np.tile(_IDENTITY, (n, 1))
    ets = np.linspace(0.0, 100.0, n)
    kf = extract_keyframes(quats, ets, math.radians(0.1))
    assert kf[0] == 0 and kf[-1] == n - 1
    assert len(kf) == 2


def test_extract_keyframes_constant_rate_rotation() -> None:
    """Constant ω about a constant axis is exactly representable by SLERP —
    the adaptive walker shouldn't need more than a handful of keyframes."""
    n = 5000
    ets = np.linspace(0.0, 100.0, n)
    rate = math.radians(10.0)  # 10°/s
    quats = np.empty((n, 4))
    for i, et in enumerate(ets):
        half = rate * et / 2.0
        quats[i] = [math.cos(half), math.sin(half), 0.0, 0.0]
    kf = extract_keyframes(quats, ets, math.radians(0.1))
    # SLERP takes the short way, forcing a chunk every ~180° to avoid wrap-around;
    # 20 leaves slack over the ~6 actually needed.
    assert 2 < len(kf) <= 20
    assert kf[0] == 0 and kf[-1] == n - 1


# ── Baseline spin fit ────────────────────────────────────────────────────


def test_fit_spin_baseline_matches_synthetic_rate() -> None:
    n = 500
    ets = np.linspace(0.0, 10.0, n)
    axis_true = np.array([0.0, 0.0, 1.0])
    rate_true = math.radians(30.0)  # 30°/s about +Z
    quats = np.empty((n, 4))
    for i, et in enumerate(ets):
        half = rate_true * et / 2.0
        quats[i] = [math.cos(half), 0.0, 0.0, math.sin(half)]
    bl = fit_spin_baseline(quats, ets, t0=0.0)
    # Axis may be sign-flipped; only rate magnitude must match.
    # Tolerance reflects O(dt²) central-diff error at this 50 Hz sample rate.
    assert abs(bl.rate_rad_s - rate_true) < 1e-4
    assert np.allclose(np.abs(bl.axis), np.abs(axis_true), atol=1e-4)
    assert np.allclose(bl.anchor, quats[0])
    assert bl.t0 == 0.0


def test_baseline_residual_is_identity_for_pure_spin() -> None:
    """If truth is exactly a constant-rate spin, the baseline residual should
    collapse it to identity quaternions at every sample."""
    n = 500
    ets = np.linspace(0.0, 10.0, n)
    rate = math.radians(30.0)
    quats = np.empty((n, 4))
    for i, et in enumerate(ets):
        half = rate * et / 2.0
        quats[i] = [math.cos(half), 0.0, 0.0, math.sin(half)]
    bl = fit_spin_baseline(quats, ets, t0=0.0)
    for i, et in enumerate(ets):
        r = bl.residual(float(et), quats[i])
        assert angle_between(r, _IDENTITY) < 1e-3


D = 86400.0


class TestShardPlanning:
    """Shard grid, CK lists per shard, span edges and the fallback instruments."""

    def test_shards_overlapping_uses_open_overlap(self) -> None:
        from space_map_data.export.position.probes.attitude.shards import (
            SHARD_S,
            shards_overlapping,
        )

        assert list(shards_overlapping(0.0, SHARD_S)) == [0]
        assert list(shards_overlapping(SHARD_S, SHARD_S)) == []
        assert list(shards_overlapping(-1.0, 1.0)) == [-1, 0]
        assert list(shards_overlapping(3 * SHARD_S, 2 * SHARD_S)) == []

    def test_plan_shards_lists_covering_cks_in_index_order(self) -> None:
        from space_map_data.export.position.probes.attitude.shards import (
            SHARD_S,
            plan_shards,
        )

        # Weekly CKs offset from the grid, plus a CK for another instrument
        # that the frame can chain through.
        coverage = {
            "b.bc": {-74000: [(3 * D, 10 * D)]},
            "a.bc": {-74000: [(10 * D, 17 * D)]},
            "chain.bc": {-74999: [(0.0, 30 * D)]},
        }
        names = ["b.bc", "a.bc", "chain.bc"]
        plan = plan_shards(coverage, names, [-74000], (3 * D, 17 * D))
        assert plan == {
            0: ["b.bc", "chain.bc"],
            1: ["b.bc", "a.bc", "chain.bc"],
            2: ["a.bc", "chain.bc"],
        }
        # The span bounds the shards, so a long claim does not add empty ones.
        plan = plan_shards(coverage, names, [-74999], (0.0, SHARD_S))
        assert list(plan) == [0]

    def test_probe_instruments_falls_back_to_carried_ids(self) -> None:
        from space_map_data.export.position.probes.attitude.shards import (
            probe_instruments,
        )

        assert probe_instruments({"x": {-91000: [(0.0, 1.0)]}}, -91000) == [-91000]
        coverage = {"x": {-91002: [(0.0, 1.0)]}, "y": {-91001: [(0.0, 1.0)]}}
        assert probe_instruments(coverage, -91000) == [-91002, -91001]

    def test_span_edges_scans_only_long_windows(self) -> None:
        from space_map_data.export.position.probes.attitude.shards import (
            span_edges,
        )

        calls: list[tuple[float, float, bool]] = []

        def scan(start: float, end: float, forward: bool) -> float | None:
            calls.append((start, end, forward))
            # Only the first 4 h of a long claim resolve, like HUYGENS.
            return start if forward else start + 4 * 3600.0

        windows = [(0.0, 7 * D), (8 * D, 16_000 * D)]
        assert span_edges(windows, scan) == (0.0, 8 * D + 4 * 3600.0)
        assert calls == [(8 * D, 16_000 * D, False)]
        assert span_edges([], scan) is None

    def test_span_edges_skips_a_claim_that_never_resolves(self) -> None:
        from space_map_data.export.position.probes.attitude.shards import (
            span_edges,
        )

        windows = [(0.0, 7 * D), (5 * D, 16_000 * D)]
        assert span_edges(windows, lambda a, b, fwd: None) == (0.0, 7 * D)


class TestValidateWindows:
    """The guard for CKs that claim more coverage than they hold."""

    def test_shard_of_a_long_claim_is_probed(self, monkeypatch) -> None:
        from space_map_data.export.position.probes.attitude import extractor
        from space_map_data.export.position.probes.attitude.shards import (
            shard_bounds,
        )

        # A 45-year claim where only 4 h resolve, as for HUYGENS.
        claim = (0.0, 45 * 365 * D)
        real = (100 * D, 100 * D + 4 * 3600.0)
        probes: list[float] = []

        def resolves(frame: str, et: float) -> bool:
            probes.append(et)
            return real[0] <= et <= real[1]

        monkeypatch.setattr(extractor, "_resolves", resolves)
        whole, claimed, kept = extractor._validate_windows("F", [claim])
        assert claimed == claim[1] and kept < D
        for k in (13, 14, 15, 200):
            lo, hi = shard_bounds(k)
            probes.clear()
            out, _, _ = extractor._validate_windows("F", [claim], lo, hi)
            clipped = [
                (max(a, lo), min(b, hi)) for a, b in whole if max(a, lo) < min(b, hi)
            ]
            assert out == clipped
            # Only the grid near the shard is probed.
            assert probes and len(probes) < 200

    def test_short_window_is_clipped_only(self) -> None:
        from space_map_data.export.position.probes.attitude import extractor

        out, claimed, _ = extractor._validate_windows("F", [(0.0, 9 * D)], 2 * D, 5 * D)
        assert out == [(2 * D, 5 * D)]
        assert claimed == 0.0


class TestShardSignature:
    """A shard signature changes only with the inputs of that shard."""

    @staticmethod
    def _sig(stamps: dict, cks: list[str], spans=None, kernels="k1") -> str:
        from space_map_data.export.position.probes.attitude.shards import (
            shard_signature,
        )

        probe = {"version": 4, "frame": "F", "bus": -74000, "kernels": kernels}
        return shard_signature(probe, [[n, stamps[n]] for n in cks], spans)

    def test_changed_ck_changes_only_its_shards(self) -> None:
        old = {"a": {"digest": "1"}, "b": {"digest": "2"}}
        new = {"a": {"digest": "1"}, "b": {"digest": "3"}}
        assert self._sig(old, ["a"]) == self._sig(new, ["a"])
        assert self._sig(old, ["a", "b"]) != self._sig(new, ["a", "b"])
        # Load order sets SPICE priority, so it is part of the signature.
        assert self._sig(old, ["a", "b"]) != self._sig(old, ["b", "a"])
        assert self._sig(old, ["a"]) != self._sig(old, ["a"], kernels="k2")

    def test_spinner_signature_uses_spans_clipped_to_the_shard(self) -> None:
        from space_map_data.export.position.probes.attitude.baseline import (
            SpinBaseline,
        )
        from space_map_data.export.position.probes.attitude.segments import (
            SpinSegment,
        )
        from space_map_data.export.position.probes.attitude.shards import (
            SHARD_S,
            shard_spans,
        )

        b = SpinBaseline(np.array([0.0, 0.0, 1.0]), 0.2, np.array([1.0, 0, 0, 0]), 0.0)
        before = [SpinSegment(0.0, 9.5 * SHARD_S, b)]
        grown = [SpinSegment(0.0, 11 * SHARD_S, b)]
        stamps = {"a": {"digest": "1"}}
        # A span that grows changes only the shard where it used to end.
        assert self._sig(stamps, ["a"], shard_spans(3, before)) == self._sig(
            stamps, ["a"], shard_spans(3, grown)
        )
        assert self._sig(stamps, ["a"], shard_spans(9, before)) != self._sig(
            stamps, ["a"], shard_spans(9, grown)
        )
        two = [
            SpinSegment(0.0, 9.5 * SHARD_S, b),
            SpinSegment(9.5 * SHARD_S, 11 * SHARD_S, b),
        ]
        spans = shard_spans(9, two)
        assert [(i, s.start_et, s.end_et) for i, s in spans] == [
            (0, 9 * SHARD_S, 9.5 * SHARD_S),
            (1, 9.5 * SHARD_S, 10 * SHARD_S),
        ]


class TestJoinShards:
    """Joining shard keyframes into one stream per spin span."""

    def test_boundary_duplicate_is_dropped(self) -> None:
        from space_map_data.export.position.probes.attitude.shards import (
            join_shards,
        )

        q = np.tile([1.0, 0.0, 0.0, 0.0], (3, 1))
        a = (np.array([0.0, 5.0, 10.0]), q, np.zeros(3, dtype=np.int16))
        b = (np.array([10.0, 15.0, 20.0]), q, np.zeros(3, dtype=np.int16))
        [(ets, quats)] = join_shards([a, b], 1)
        assert ets.tolist() == [0.0, 5.0, 10.0, 15.0, 20.0]
        assert quats.shape == (5, 4)

    def test_streams_split_by_span_and_rise_strictly(self) -> None:
        from space_map_data.export.position.probes.attitude.shards import (
            join_shards,
        )

        q = np.tile([1.0, 0.0, 0.0, 0.0], (4, 1))
        # The span boundary at 10 is sampled in both spans.
        a = (np.array([0.0, 10.0, 10.0, 12.0]), q, np.array([0, 0, 1, 1], np.int16))
        b = (np.array([12.0, 11.0, 14.0, 16.0]), q, np.array([1, 1, 1, 1], np.int16))
        (e0, _), (e1, _), (e2, _) = join_shards([a, b], 3)
        assert e0.tolist() == [0.0, 10.0]
        assert e1.tolist() == [10.0, 12.0, 14.0, 16.0]
        assert e2.size == 0

    def test_split_runs_cuts_gaps_and_cost(self) -> None:
        from space_map_data.export.position.probes.attitude.shards import (
            split_runs,
        )

        ks = [1, 2, 3, 4, 7, 8]
        assert split_runs(ks, lambda k: 1.0, 10.0) == [[1, 2, 3, 4], [7, 8]]
        assert split_runs(ks, lambda k: 1.0, 2.0) == [[1, 2], [3, 4], [7, 8]]
        assert split_runs([5], lambda k: 9.0, 2.0) == [[5]]


class TestAttitudeCache:
    """Per-probe incremental cache: an unchanged probe skips re-extraction and
    re-injects its manifest; a kernel change re-extracts."""

    @staticmethod
    def _fake_result(probe_out_dir):
        """Stub an `extract_attitude` that writes one chunk + returns its result."""
        from space_map_data.export.position.probes.attitude.extractor import (
            ExtractionResult,
        )
        from space_map_data.export.position.probes.attitude.writer import ChunkFile

        probe_out_dir.mkdir(parents=True, exist_ok=True)
        (probe_out_dir / "0.bin.gz").write_bytes(b"chunk")
        return ExtractionResult(
            n_keyframes=10,
            files=[
                ChunkFile(
                    name="0.bin.gz",
                    start_jd=2454046.5,
                    end_jd=2454047.5,
                    n_keyframes=10,
                    baseline_index=0,
                )
            ],
            segments=[],
            coverage_start_jd=2454046.5,
            coverage_end_jd=2454047.5,
        )

    def _run(self, monkeypatch, out_dir, stamps, calls):
        from space_map_data.export.position.probes.attitude import orchestrator

        def fake_extract(probe_out_dir, ck_paths, bus_instr_id, frame_name):
            calls.append(bus_instr_id)
            return self._fake_result(probe_out_dir)

        monkeypatch.setattr(orchestrator, "extract_attitude", fake_extract)
        global_data: dict[str, dict] = {"probe-7": {}}
        summary: dict[str, dict] = {}
        job = orchestrator._plan_probe(
            out_dir,
            {"probe_id": 7, "kernel_sources": [{"mission": "M", "naif_id": -82}]},
            "M",
            {"frame_name": "FRAME"},
            stamps,
            global_data,
            summary,
        )
        if job is not None:
            res = orchestrator._extract_probe(out_dir, "FRAME", ["/ck/a.bc"], job)
            orchestrator._apply_result("M", res, global_data, summary)
        return global_data, summary

    def test_second_run_skips_extraction(self, monkeypatch, tmp_path) -> None:
        calls: list[int] = []
        stamps = {"ck/a.bc": {"size": 2, "digest": "aa"}}
        gd1, _s1 = self._run(monkeypatch, tmp_path, stamps, calls)
        gd2, s2 = self._run(monkeypatch, tmp_path, stamps, calls)
        assert len(calls) == 1  # second run served from cache
        assert s2["7"]["cached"] is True
        # Manifest re-injected on the cache hit even though nothing re-extracted.
        assert gd1["probe-7"]["attitude"] == gd2["probe-7"]["attitude"]
        assert gd2["probe-7"]["attitude"]["n_keyframes"] == 10

    def test_kernel_change_reextracts(self, monkeypatch, tmp_path) -> None:
        calls: list[int] = []
        self._run(
            monkeypatch, tmp_path, {"ck/a.bc": {"size": 2, "digest": "aa"}}, calls
        )
        self._run(
            monkeypatch, tmp_path, {"ck/a.bc": {"size": 2, "digest": "bb"}}, calls
        )
        assert len(calls) == 2  # changed stamp invalidated the cache

    def test_missing_chunk_invalidates_cache(self, monkeypatch, tmp_path) -> None:
        calls: list[int] = []
        stamps = {"ck/a.bc": {"size": 2, "digest": "aa"}}
        self._run(monkeypatch, tmp_path, stamps, calls)
        (tmp_path / "attitude" / "7" / "0.bin.gz").unlink()
        self._run(monkeypatch, tmp_path, stamps, calls)
        assert len(calls) == 2  # vanished chunk forces a rebuild


def test_enforce_min_span_drops_slivers() -> None:
    """Boundaries closer than the min span collapse, so a brief blip can't
    carve a sliver segment."""
    from space_map_data.export.position.probes.attitude.segments import (
        SEG_MIN_S,
        _enforce_min_span,
    )

    t0, t1 = 0.0, 100.0 * SEG_MIN_S
    # Two well-separated transitions survive; a pair packed within one min span
    # collapses to a single boundary; one hugging the end is dropped.
    raw = [10 * SEG_MIN_S, 10.4 * SEG_MIN_S, 50 * SEG_MIN_S, t1 - 0.1 * SEG_MIN_S]
    kept = _enforce_min_span(raw, t0, t1)
    assert kept == [10 * SEG_MIN_S, 50 * SEG_MIN_S]
