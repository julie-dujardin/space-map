"""Attitude stack unit tests: wire format, quaternions, keyframe extraction,
baseline spin fit — all synthetic, no kernels needed. The cached-CK
end-to-end smoke lives in `scripts/probe_orientation_smoke.py`.
"""

import itertools
import math
import struct
from pathlib import Path

import numpy as np
import pytest

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

    def test_probe_instruments_falls_back_to_the_crafts_own_ids(self) -> None:
        from space_map_data.export.position.probes.attitude.shards import (
            probe_instruments,
        )

        assert probe_instruments({"x": {-91000: [(0.0, 1.0)]}}, -91000) == [-91000]
        coverage = {"x": {-91002: [(0.0, 1.0)]}, "y": {-91001: [(0.0, 1.0)]}}
        assert probe_instruments(coverage, -91000) == [-91002, -91001]

    def test_probe_instruments_leaves_out_what_another_craft_carries(self) -> None:
        from space_map_data.export.position.probes.attitude.shards import (
            probe_instruments,
        )

        window = [(0.0, 1.0)]
        # The OSIRIS-REx bus and solar array gimbals, and its capsule -64090.
        coverage = {"x": {-64000: window, -64012: window, -64022: window}}
        assert probe_instruments(coverage, -64000) == [-64000]
        assert probe_instruments(coverage, -64090000) == []
        # A second craft of the mission, with a lower ID.
        assert probe_instruments({"x": {-31000: window}}, -32000) == []

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
    def _sig(stamps: dict, cks: list[str], spans=None, kernels="k1", clock="c") -> str:
        from space_map_data.export.position.probes.attitude.shards import (
            shard_signature,
        )

        probe = {"version": 4, "frame": "F", "bus": -74000, "kernels": kernels}
        return shard_signature(probe, [[n, stamps[n]] for n in cks], spans, clock)

    def test_changed_ck_changes_only_its_shards(self) -> None:
        old = {"a": {"digest": "1"}, "b": {"digest": "2"}}
        new = {"a": {"digest": "1"}, "b": {"digest": "3"}}
        assert self._sig(old, ["a"]) == self._sig(new, ["a"])
        assert self._sig(old, ["a", "b"]) != self._sig(new, ["a", "b"])
        # Load order sets SPICE priority, so it is part of the signature.
        assert self._sig(old, ["a", "b"]) != self._sig(old, ["b", "a"])
        assert self._sig(old, ["a"]) != self._sig(old, ["a"], kernels="k2")
        assert self._sig(old, ["a"]) != self._sig(old, ["a"], clock="c2")

    def test_clock_signature_takes_the_rows_that_reach_the_shard(self) -> None:
        from space_map_data.export.position.probes.attitude.shards import (
            SHARD_S,
            clock_signature,
        )

        old = np.array([[0.0, 0.0, 1.0], [10.0, 2.5 * SHARD_S, 1.0]])
        # The new SCLK revises the last rate and adds a row.
        new = np.array(
            [[0.0, 0.0, 1.0], [10.0, 2.5 * SHARD_S, 1.1], [20.0, 4.5 * SHARD_S, 1.0]]
        )
        assert [
            clock_signature(old, k) == clock_signature(new, k) for k in range(5)
        ] == [True, True, False, False, False]

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
    """The run extracts only stale shards and writes chunks only when needed.

    The worker tasks are fakes that need no SPICE. Each CK covers one week
    with a fixed offset from the shard grid.
    """

    @staticmethod
    def _mission(tmp_path, stamps: dict[str, str], sclk: str = "s"):
        from space_map_data.export.position.probes.attitude import orchestrator
        from space_map_data.export.position.probes.attitude.cache import (
            load_probe_cache,
        )

        out_dir = tmp_path / "export"
        probe_out = out_dir / "attitude" / "7"
        probe = orchestrator._Probe(
            probe_id=7,
            bus=-82000,
            out_dir=probe_out,
            meta_dir=probe_out,
            cache=load_probe_cache(probe_out),
        )
        names = list(stamps)
        mission = orchestrator._Craft(
            mission="M",
            mission_dir=tmp_path / "M",
            frame="FRAME",
            base=["lsk", "pck", "fk", "sclk"],
            base_stamps=[[n, {"size": 1, "digest": n}] for n in ("l", "p", "f")],
            sclk="sclk",
            sclk_stamp=[sclk, {"size": 1, "digest": sclk}],
            ck_names=names,
            ck_stamps={n: {"size": 1, "digest": d} for n, d in stamps.items()},
            ck_sizes=dict.fromkeys(names, 1),
            probes=[probe],
        )
        return out_dir, mission, probe

    def _run(
        self,
        monkeypatch,
        tmp_path,
        stamps: dict[str, str],
        calls: dict,
        *,
        unreadable: frozenset[str] = frozenset(),
        ephemeris: frozenset[str] = frozenset(),
        broken_shard_pool: bool = False,
        bases: list | None = None,
        sclk: str = "s",
        clock: tuple[tuple[float, float, float], ...] | None = ((0.0, 0.0, 1.0),),
    ):
        from concurrent.futures import ThreadPoolExecutor
        from concurrent.futures.process import BrokenProcessPool

        from space_map_data.export.position.probes.attitude import orchestrator, writer
        from space_map_data.export.position.probes.attitude.cache import save_shard
        from space_map_data.export.position.probes.attitude.shards import (
            shard_bounds,
        )
        from space_map_data.export.position.probes.attitude.worker import (
            ShardResult,
            ShardTaskResult,
        )

        def week(path: str) -> tuple[float, float]:
            i = int(path.rsplit("/", 1)[1].split(".")[0])
            return (i * 7 + 3) * D, ((i + 1) * 7 + 3) * D

        def fake_coverage(base, ck_paths):
            calls["coverage"] += len(ck_paths)
            return {
                p: "unreadable"
                if Path(p).name in unreadable
                else {
                    "cover": {-82000: [week(p)]},
                    "ephemeris": Path(p).name in ephemeris,
                }
                for p in ck_paths
            }

        def fake_sclk(path):
            if clock is None:
                raise OSError("unreadable")
            return np.array(clock)

        def fake_timeline(base, ck_paths, frame, ets):
            return [np.zeros(3) for _ in ets]

        def fake_shard(task):
            if bases is not None:
                bases.append(task.base)
            results = []
            for k, _paths in task.shards:
                lo, hi = shard_bounds(k)
                for job in task.jobs[k]:
                    calls["shards"].append(k)
                    ets = np.linspace(lo, hi, 4)
                    quats = np.tile([1.0, 0.0, 0.0, 0.0], (4, 1))
                    seg = np.zeros(4, dtype=np.int16)
                    save_shard(Path(job.out_path), ets, quats, seg)
                    results.append(ShardResult(job.probe_id, k, 4, 0, 0.0, 0.0, None))
            return ShardTaskResult(results, 0, 0.0)

        class Pool(ThreadPoolExecutor):
            def submit(self, fn, /, *args, **kwargs):
                if broken_shard_pool and fn is fake_shard:
                    raise BrokenProcessPool("a worker died")
                return super().submit(fn, *args, **kwargs)

        real_write = writer.write_chunks

        def counting_write(out_dir, segments):
            calls["writes"] += 1
            return real_write(out_dir, segments)

        monkeypatch.setattr(orchestrator, "coverage_task", fake_coverage)
        monkeypatch.setattr(orchestrator, "sclk_task", fake_sclk)
        monkeypatch.setattr(orchestrator, "timeline_task", fake_timeline)
        monkeypatch.setattr(orchestrator, "shard_task", fake_shard)
        monkeypatch.setattr(orchestrator, "write_chunks", counting_write)
        monkeypatch.setattr(
            orchestrator, "kernels_from_index", lambda mdir: [mdir / "a.bsp"]
        )
        monkeypatch.setattr(
            orchestrator,
            "content_stamps",
            lambda paths: {p: {"size": 1, "digest": p.name} for p in paths},
        )
        out_dir, mission, probe = self._mission(tmp_path, stamps, sclk)
        global_data: dict[str, dict] = {"probe-7": {}}
        summary: dict[str, dict] = {}
        with Pool(max_workers=2) as ex:
            run = orchestrator._Run(out_dir, ex, n_workers=2)
            run.read_coverage([mission])
            run.read_clocks([mission])
            run.plan_spins([mission])
            run.extract([mission], global_data, summary)
        return global_data, summary, probe

    @staticmethod
    def _calls() -> dict:
        return {"coverage": 0, "shards": [], "writes": 0}

    def test_second_run_extracts_nothing(self, monkeypatch, tmp_path) -> None:
        stamps = {"0.bc": "a", "1.bc": "b", "2.bc": "c"}
        first = self._calls()
        gd1, s1, _ = self._run(monkeypatch, tmp_path, stamps, first)
        assert sorted(first["shards"]) == [0, 1, 2, 3]
        assert first["coverage"] == 3
        assert s1["7"]["cached"] is False
        second = self._calls()
        gd2, s2, _ = self._run(monkeypatch, tmp_path, stamps, second)
        assert second == {"coverage": 0, "shards": [], "writes": 0}
        assert s2["7"]["cached"] is True
        assert gd1["probe-7"]["attitude"] == gd2["probe-7"]["attitude"]
        # Four shards of four keyframes, less the three shared edge samples.
        assert gd2["probe-7"]["attitude"]["n_keyframes"] == 13

    def test_changed_ck_extracts_only_its_shards(self, monkeypatch, tmp_path) -> None:
        self._run(monkeypatch, tmp_path, {"0.bc": "a", "1.bc": "b"}, self._calls())
        calls = self._calls()
        _, summary, _ = self._run(
            monkeypatch, tmp_path, {"0.bc": "a", "1.bc": "B"}, calls
        )
        assert calls["coverage"] == 1
        assert sorted(calls["shards"]) == [1, 2]
        assert calls["writes"] == 1
        assert summary["7"]["cached"] is False

    def test_new_sclk_extracts_only_the_shards_its_rows_reach(
        self, monkeypatch, tmp_path
    ) -> None:
        from space_map_data.export.position.probes.attitude.shards import SHARD_S

        stamps = {"0.bc": "a", "1.bc": "b", "2.bc": "c"}
        self._run(monkeypatch, tmp_path, stamps, self._calls())
        calls = self._calls()
        clock = ((0.0, 0.0, 1.0), (10.0, 2.5 * SHARD_S, 1.0))
        self._run(monkeypatch, tmp_path, stamps, calls, sclk="s2", clock=clock)
        assert sorted(calls["shards"]) == [2, 3]
        assert calls["writes"] == 1

    def test_ck_that_needs_positions_adds_the_mission_spks(
        self, monkeypatch, tmp_path
    ) -> None:
        bases: list = []
        stamps = {"0.bc": "a", "1.bc": "b"}
        _, _, plain = self._run(monkeypatch, tmp_path, stamps, self._calls())
        assert len(plain.probe_sig["kernels"]) == 3
        _, _, probe = self._run(
            monkeypatch,
            tmp_path / "eph",
            stamps,
            self._calls(),
            ephemeris=frozenset({"1.bc"}),
            bases=bases,
        )
        spk = str(tmp_path / "eph" / "M" / "a.bsp")
        assert probe.probe_sig["kernels"][:3] == plain.probe_sig["kernels"]
        assert probe.probe_sig["kernels"][3][1] == {"size": 1, "digest": "a.bsp"}
        assert bases and all(base[-1] == spk for base in bases)
        assert set(probe.planned.values()).isdisjoint(plain.planned.values())

    def test_missing_chunk_rewrites_chunks_only(self, monkeypatch, tmp_path) -> None:
        stamps = {"0.bc": "a"}
        self._run(monkeypatch, tmp_path, stamps, self._calls())
        (tmp_path / "export" / "attitude" / "7" / "0.bin.gz").unlink()
        calls = self._calls()
        self._run(monkeypatch, tmp_path, stamps, calls)
        assert calls["shards"] == []
        assert calls["writes"] == 1
        assert (tmp_path / "export" / "attitude" / "7" / "0.bin.gz").exists()

    def test_dropped_ck_prunes_its_shards(self, monkeypatch, tmp_path) -> None:
        from space_map_data.export.position.probes.attitude.cache import list_shards

        self._run(monkeypatch, tmp_path, {"0.bc": "a", "1.bc": "b"}, self._calls())
        calls = self._calls()
        _, _, probe = self._run(monkeypatch, tmp_path, {"0.bc": "a"}, calls)
        assert calls["shards"] == [1]
        assert sorted(int(n.split("-")[0]) for n in list_shards(probe.meta_dir)) == [
            0,
            1,
        ]

    def test_failed_coverage_read_keeps_shards_and_chunks(
        self, monkeypatch, tmp_path
    ) -> None:
        from space_map_data.export.position.probes.attitude.cache import list_shards

        self._run(monkeypatch, tmp_path, {"0.bc": "a", "1.bc": "b"}, self._calls())
        probe_dir = tmp_path / "export" / "attitude" / "7"
        shards = list_shards(probe_dir)
        chunks = sorted(probe_dir.glob("*.bin.gz"))
        stamps = {"0.bc": "a", "1.bc": "B"}
        calls = self._calls()
        gd, summary, _ = self._run(
            monkeypatch,
            tmp_path,
            stamps,
            calls,
            unreadable=frozenset({"1.bc"}),
        )
        assert calls == {"coverage": 1, "shards": [], "writes": 0}
        assert "attitude" not in gd["probe-7"]
        assert summary == {}
        assert list_shards(probe_dir) == shards
        assert sorted(probe_dir.glob("*.bin.gz")) == chunks
        # The CK reads again and only its shards extract.
        calls = self._calls()
        gd, _, _ = self._run(monkeypatch, tmp_path, stamps, calls)
        assert calls["coverage"] == 1
        assert sorted(calls["shards"]) == [1, 2]
        assert gd["probe-7"]["attitude"]["n_keyframes"] == 10

    def test_failed_sclk_read_keeps_shards_and_chunks(
        self, monkeypatch, tmp_path
    ) -> None:
        from space_map_data.export.position.probes.attitude.cache import list_shards

        stamps = {"0.bc": "a", "1.bc": "b"}
        self._run(monkeypatch, tmp_path, stamps, self._calls())
        probe_dir = tmp_path / "export" / "attitude" / "7"
        shards = list_shards(probe_dir)
        chunks = sorted(probe_dir.glob("*.bin.gz"))
        calls = self._calls()
        gd, summary, _ = self._run(monkeypatch, tmp_path, stamps, calls, clock=None)
        assert calls == {"coverage": 0, "shards": [], "writes": 0}
        assert "attitude" not in gd["probe-7"]
        assert summary == {}
        assert list_shards(probe_dir) == shards
        assert sorted(probe_dir.glob("*.bin.gz")) == chunks

    def test_broken_pool_keeps_shards_and_chunks(self, monkeypatch, tmp_path) -> None:
        from space_map_data.export.position.probes.attitude.cache import list_shards

        self._run(monkeypatch, tmp_path, {"0.bc": "a", "1.bc": "b"}, self._calls())
        probe_dir = tmp_path / "export" / "attitude" / "7"
        shards = list_shards(probe_dir)
        calls = self._calls()
        gd, summary, _ = self._run(
            monkeypatch,
            tmp_path,
            {"0.bc": "a", "1.bc": "B"},
            calls,
            broken_shard_pool=True,
        )
        assert calls["writes"] == 0
        assert "attitude" not in gd["probe-7"]
        assert summary == {}
        assert list_shards(probe_dir) == shards

    def test_unreadable_shard_is_extracted_again(self, monkeypatch, tmp_path) -> None:
        from space_map_data.export.position.probes.attitude.cache import list_shards

        stamps = {"0.bc": "a"}
        self._run(monkeypatch, tmp_path, stamps, self._calls())
        probe_dir = tmp_path / "export" / "attitude" / "7"
        bad = min(list_shards(probe_dir))
        (probe_dir / "shards" / bad).write_bytes(b"")
        (probe_dir / "0.bin.gz").unlink()
        _, summary, _ = self._run(monkeypatch, tmp_path, stamps, self._calls())
        assert summary == {}
        assert bad not in list_shards(probe_dir)
        calls = self._calls()
        gd, _, _ = self._run(monkeypatch, tmp_path, stamps, calls)
        assert calls["shards"] == [int(bad.split("-")[0])]
        assert "attitude" in gd["probe-7"]


class TestCraft:
    """A mission index holds one entry per craft, and each probe takes its
    attitude only from the craft whose CKs carry its instruments."""

    @staticmethod
    def _load(monkeypatch, tmp_path, indexes: dict[str, str], registry: list[dict]):
        from space_map_data.export.position.probes.attitude import orchestrator

        for name, text in indexes.items():
            (tmp_path / name).mkdir()
            (tmp_path / name / orchestrator.ATTITUDE_INDEX_NAME).write_text(text)
        monkeypatch.setattr(orchestrator, "MISSIONS_DIR", tmp_path)
        monkeypatch.setattr(orchestrator, "load_registry", lambda: registry)
        monkeypatch.setattr(
            orchestrator,
            "content_stamps",
            lambda paths: {p: {"size": 1, "digest": p.name} for p in paths},
        )
        return orchestrator._load_crafts(tmp_path / "export")

    @staticmethod
    def _entry(probe_id: int, naif: int, mission: str = "M") -> dict:
        return {
            "probe_id": probe_id,
            "kernel_sources": [{"mission": mission, "naif_id": naif}],
        }

    def test_each_craft_keeps_the_probes_its_cks_carry(
        self, monkeypatch, tmp_path
    ) -> None:
        import json
        from concurrent.futures import ThreadPoolExecutor

        from space_map_data.export.position.probes.attitude import orchestrator
        from space_map_data.export.position.probes.attitude.cache import coverage_path

        craft = [
            {"frame_name": f, "fk": f"{f}.tf", "sclk": f"{f}.tsc", "ck_files": [ck]}
            for f, ck in (("ONE", "1.bc"), ("TWO", "2.bc"))
        ]
        missions = self._load(
            monkeypatch,
            tmp_path,
            {"M": json.dumps({"spacecraft": craft})},
            # Two craft, and a lander with no CK.
            [self._entry(1, -31), self._entry(2, -32), self._entry(3, -327)],
        )
        instruments = {"1.bc": -31000, "2.bc": -32000}

        def fake_coverage(base, ck_paths):
            return {
                p: {
                    "cover": {instruments[Path(p).name]: [(0.0, D)]},
                    "ephemeris": False,
                }
                for p in ck_paths
            }

        monkeypatch.setattr(orchestrator, "coverage_task", fake_coverage)
        out_dir = tmp_path / "export"
        with ThreadPoolExecutor(max_workers=2) as ex:
            orchestrator._Run(out_dir, ex, n_workers=2).read_coverage(missions)
        assert [[p.probe_id for p in m.probes] for m in missions] == [[1], [2]]
        assert [m.frame for m in missions] == ["ONE", "TWO"]
        assert missions[1].base[2:] == [
            str(tmp_path / "M" / "TWO.tf"),
            str(tmp_path / "M" / "TWO.tsc"),
        ]
        for m in missions:
            assert coverage_path(out_dir / "attitude", m.frame).exists()

    def test_unreadable_index_leaves_out_only_its_mission(
        self, monkeypatch, tmp_path
    ) -> None:
        import json

        craft = {"frame_name": "F", "fk": "f", "sclk": "s", "ck_files": ["0.bc"]}
        missions = self._load(
            monkeypatch,
            tmp_path,
            {"A": "{", "B": json.dumps({"spacecraft": [craft]})},
            [self._entry(7, -82, "A"), self._entry(8, -83, "B")],
        )
        assert [m.mission for m in missions] == ["B"]

    def test_probe_with_two_ids_in_a_mission_is_one_probe(
        self, monkeypatch, tmp_path
    ) -> None:
        import json

        craft = {"frame_name": "F", "fk": "f", "sclk": "s", "ck_files": ["0.bc"]}
        entry = {
            "probe_id": 7,
            "kernel_sources": [
                {"mission": "M", "naif_id": -102},
                {"mission": "M", "naif_id": -101},
            ],
        }
        missions = self._load(
            monkeypatch,
            tmp_path,
            {"M": json.dumps({"spacecraft": [craft]})},
            [entry],
        )
        assert [p.probe_id for p in missions[0].probes] == [7]


def test_span_with_fewer_probes_than_workers_plans(monkeypatch, tmp_path) -> None:
    """A span of a few seconds has fewer timeline probes than workers."""
    from concurrent.futures import ThreadPoolExecutor

    from space_map_data.export.position.probes.attitude import orchestrator
    from space_map_data.export.position.probes.attitude.segments import (
        SpinSegment,
    )

    monkeypatch.setattr(
        orchestrator,
        "timeline_task",
        lambda base, ck_paths, frame, ets: [np.zeros(3) for _ in ets],
    )
    out_dir, mission, probe = TestAttitudeCache._mission(tmp_path, {"0.bc": "a"})
    mission.coverage = {"0.bc": {-82000: [(100.0, 103.0)]}}
    probe.instruments = [-82000]
    with ThreadPoolExecutor(max_workers=2) as ex:
        orchestrator._Run(out_dir, ex, n_workers=12).plan_spins([mission])
    assert probe.error is None
    assert probe.segments == [SpinSegment(100.0, 103.0, None)]


def test_spin_timeline_keeps_earlier_probes_when_the_span_grows() -> None:
    from space_map_data.export.position.probes.attitude.segments import (
        SEG_MAX_PROBES,
        spin_timeline_ets,
    )

    t0 = 123.4
    week = spin_timeline_ets(t0, 400 * D)
    grown = spin_timeline_ets(t0, 407 * D)
    assert week[0] == grown[0] == t0
    assert np.array_equal(grown[: week.size], week)
    step = week[2] - week[1]
    assert math.log2(step).is_integer()
    assert np.all(week[1:] % step == 0) and np.all(np.diff(week) > 0)
    assert SEG_MAX_PROBES / 2 <= week.size <= SEG_MAX_PROBES + 1


RPM = 2 * math.pi / 60


class TestSpinPlan:
    """The planner on a synthetic spin about +Z, with SPICE faked."""

    @staticmethod
    def _plan(monkeypatch, phi, t1: float, t0: float = 0.0):
        import spiceypy

        from space_map_data.export.position.probes.attitude.adaptive import (
            SEED_DT_S,
        )
        from space_map_data.export.position.probes.attitude.extractor import (
            ALIAS_ANGLE_RAD,
        )
        from space_map_data.export.position.probes.attitude.segments import (
            plan_segments,
        )

        def pxform(_from: str, _to: str, et: float) -> np.ndarray:
            half = 0.5 * phi(et)
            return np.array([math.cos(half), 0.0, 0.0, math.sin(half)])

        monkeypatch.setattr(spiceypy, "pxform", pxform)
        monkeypatch.setattr(spiceypy, "m2q", lambda q: q)
        return plan_segments(
            "F", t0, t1, alias_angle=ALIAS_ANGLE_RAD, seed_dt=SEED_DT_S
        )

    @staticmethod
    def _assert_holds(phi, seg) -> None:
        """The residual against the span's baseline turns at most 90° per
        300 s anywhere in the span."""
        b = seg.baseline
        rate = b.rate_rad_s * float(np.sign(b.axis[2]))
        for et in np.linspace(seg.start_et, seg.end_et - 300.0, 40):
            turn = phi(et + 300.0) - phi(et) - rate * 300.0
            assert abs(turn) <= math.pi / 2 + 1e-6

    def test_drifting_spin_is_cut_where_its_baseline_stops_holding(
        self, monkeypatch
    ) -> None:
        w0, accel = 2.2 * RPM, -0.4 * RPM / D

        def phi(t: float) -> float:
            return w0 * t + 0.5 * accel * t * t

        segs = self._plan(monkeypatch, phi, D)
        assert len(segs) > 4
        assert all(s.baseline is not None and s.seed_dt == 300.0 for s in segs)
        assert all(a.end_et == b.start_et for a, b in itertools.pairwise(segs))
        for seg in segs:
            self._assert_holds(phi, seg)

    def test_more_data_keeps_the_earlier_spans(self, monkeypatch) -> None:
        """A CK that adds a day after the span moves no earlier span edge or
        baseline."""
        w0, accel = 2.2 * RPM, -0.04 * RPM / D

        def phi(t: float) -> float:
            return w0 * t + 0.5 * accel * t * t

        t0 = 1234.5
        short = self._plan(monkeypatch, phi, 10 * D, t0)
        grown = self._plan(monkeypatch, phi, 11 * D, t0)
        assert len(grown) >= len(short) > 4
        for a, b in zip(short, grown, strict=False):
            assert (a.start_et, a.seed_dt) == (b.start_et, b.seed_dt)
            assert a.baseline.rate_rad_s == b.baseline.rate_rad_s
            assert np.array_equal(a.baseline.anchor, b.baseline.anchor)
        ends = [s.end_et for s in grown[: len(short) - 1]]
        assert [s.end_et for s in short[:-1]] == ends

    def test_spin_step_keeps_one_span_per_phase(self, monkeypatch) -> None:
        """A Juno spin change ramps for two minutes: one cut, no raw sliver."""
        w1, w2, step_at, ramp = 1.0 * RPM, 2.0 * RPM, 20 * D, 120.0

        def phi(t: float) -> float:
            if t < step_at:
                return w1 * t
            u = min(t - step_at, ramp)
            ramped = w1 * step_at + w1 * u + (w2 - w1) * u * u / (2 * ramp)
            return ramped + w2 * max(0.0, t - step_at - ramp)

        segs = self._plan(monkeypatch, phi, 40 * D)
        assert [s.baseline is not None for s in segs] == [True, True]
        assert step_at <= segs[1].start_et <= step_at + ramp
        rates = [s.baseline.rate_rad_s / RPM for s in segs if s.baseline]
        assert rates == pytest.approx([1.0, 2.0], abs=1e-3)

    def test_fast_changing_spin_gets_a_raw_span(self, monkeypatch) -> None:
        """A steady spin, then a rate that swings between 1 and 5 RPM every
        ten minutes, like the HUYGENS descent."""
        steady, period = 6 * 3600.0, 600.0

        def phi(t: float) -> float:
            if t < steady:
                return 5 * RPM * t
            u = t - steady
            swing = (
                2
                * RPM
                * period
                / (2 * math.pi)
                * (1 - math.cos(2 * math.pi * u / period))
            )
            return 5 * RPM * steady + 3 * RPM * u + swing

        t1 = steady + 2 * 3600.0
        segs = self._plan(monkeypatch, phi, t1)
        *steady_spans, raw = segs
        assert steady_spans and all(s.baseline is not None for s in steady_spans)
        assert raw.baseline is None and raw.end_et == t1
        assert steady - 600.0 <= raw.start_et <= steady
        # The top rate is 5 RPM, so a seed step turns the craft 90°.
        assert raw.seed_dt == pytest.approx(math.pi / 2 / (5 * RPM), rel=1e-3)

    def test_spin_up_after_the_coverage_start_is_raw(self, monkeypatch) -> None:
        """HUYGENS sits still on Cassini for the first minutes of its CK."""
        spin_up = 200.0

        def phi(t: float) -> float:
            return 2 * RPM * max(0.0, t - spin_up)

        segs = self._plan(monkeypatch, phi, D)
        assert [s.baseline is not None for s in segs] == [False, True]
        assert spin_up - 10.0 <= segs[0].end_et <= spin_up
        assert segs[0].seed_dt == 300.0
        assert segs[1].baseline.rate_rad_s / RPM == pytest.approx(2.0, rel=1e-4)


def test_raw_span_refines_below_a_second_on_a_short_seed(monkeypatch) -> None:
    """A raw fast spin gets a refinement floor of a quarter seed step; the
    default seed step keeps the 1 s floor."""
    from space_map_data.export.position.probes.attitude import extractor
    from space_map_data.export.position.probes.attitude.segments import (
        SpinSegment,
    )

    floors: dict[float, float] = {}

    def fake_sample(frame, t0, t1, eps, *, seed_dt, min_dt, transform):
        floors[seed_dt] = min_dt
        return np.array([t0, t1]), np.tile(_IDENTITY, (2, 1)), 0

    monkeypatch.setattr(extractor, "adaptive_sample", fake_sample)
    for seg in (SpinSegment(0.0, 100.0, None, 1.6), SpinSegment(0.0, 100.0, None)):
        extractor._keyframe_segment("F", seg, [(0.0, 100.0)], 1e-3)
    assert floors == {1.6: pytest.approx(0.4), 300.0: 1.0}


class TestPointWindows:
    """A lone CK record resolves only at its instant, and the sampler must
    still keep it. The fake turns 0.5 mrad per second about Z."""

    @staticmethod
    def _spice(monkeypatch, resolves) -> None:
        import spiceypy

        def pxform(_from: str, _to: str, et: float) -> np.ndarray:
            if not resolves(et):
                raise spiceypy.exceptions.SpiceyError("gap")
            half = 0.25e-3 * et
            return np.array([math.cos(half), 0.0, 0.0, math.sin(half)])

        monkeypatch.setattr(spiceypy, "pxform", pxform)
        monkeypatch.setattr(spiceypy, "m2q", lambda q: q)

    @staticmethod
    def _keyframes(windows, end: float):
        from space_map_data.export.position.probes.attitude import extractor
        from space_map_data.export.position.probes.attitude.segments import (
            SpinSegment,
        )

        return extractor._keyframe_segment(
            "F", SpinSegment(0.0, end, None), windows, math.radians(0.1)
        )

    def test_point_windows_become_keyframes(self, monkeypatch) -> None:
        points = [(120.0 * i, 120.0 * i) for i in range(1, 500)]
        instants = {a for a, _ in points}
        self._spice(monkeypatch, instants.__contains__)
        ets, quats, n_samples, n_gaps = self._keyframes(points, 1e6)
        assert n_samples == len(points)
        assert n_gaps == 0
        assert set(ets) <= instants
        assert ets[0] == 120.0
        # A steady turn is one geodesic, so the 90 degree cap sets the cuts.
        assert ets[-1] == 120.0 * 499
        assert 2 <= ets.size < len(points) / 10
        assert quats.shape == (ets.size, 4)

    def test_points_between_long_windows_stay_in_time_order(self, monkeypatch) -> None:
        long_windows = [(0.0, 1000.0), (5000.0, 6000.0)]
        points = [(2000.0, 2000.0), (3000.0, 3000.0), (4000.0, 4000.0)]
        windows = sorted(long_windows + points)

        def covered(et: float) -> bool:
            return (0.0 <= et <= 1000.0 or 5000.0 <= et <= 6000.0) or et in {
                a for a, _ in points
            }

        self._spice(monkeypatch, covered)
        ets, _, _, n_gaps = self._keyframes(windows, 1e6)
        assert n_gaps == 0
        assert np.all(np.diff(ets) > 0)
        assert {1000.0, 4000.0, 6000.0} <= set(ets)

    def test_point_outside_the_span_is_left_out(self, monkeypatch) -> None:
        self._spice(monkeypatch, lambda _: True)
        ets, _, _, _ = self._keyframes([(10.0, 10.0), (20.0, 20.0), (50.0, 50.0)], 30.0)
        assert list(ets) == [10.0, 20.0]

    def test_instant_that_does_not_resolve_is_left_out_and_counted(
        self, monkeypatch
    ) -> None:
        self._spice(monkeypatch, lambda et: et != 20.0)
        ets, _, n_samples, n_gaps = self._keyframes(
            [(10.0, 10.0), (20.0, 20.0), (30.0, 30.0)], 100.0
        )
        assert list(ets) == [10.0, 30.0]
        assert n_samples == 2
        assert n_gaps == 1


class TestManifest:
    """The manifest a deployed frontend reads."""

    def test_raw_span_of_a_spinner_is_a_zero_rate_baseline(self) -> None:
        from space_map_data.export.position.probes.attitude.baseline import (
            SpinBaseline,
        )
        from space_map_data.export.position.probes.attitude.extractor import (
            ExtractionResult,
            manifest_entry,
        )
        from space_map_data.export.position.probes.attitude.segments import (
            SpinSegment,
        )
        from space_map_data.export.position.probes.attitude.writer import ChunkFile

        spin = SpinBaseline(np.array([0.0, 0.0, 1.0]), 0.2, _IDENTITY.copy(), 0.0)
        segments = [SpinSegment(0.0, D, spin), SpinSegment(D, 2 * D, None, 1.7)]
        files = [
            ChunkFile("0.bin.gz", 2451545.0, 2451546.0, 10, 0),
            ChunkFile("1.bin.gz", 2451546.0, 2451547.0, 10, 1),
        ]
        entry = manifest_entry(
            ExtractionResult(20, files, segments, 2451545.0, 2451547.0), frame_name="F"
        )
        raw = entry["baselines"][1]
        assert raw["kind"] == "spin" and raw["rate_rad_s"] == 0.0
        assert raw["anchor"] == [1.0, 0.0, 0.0, 0.0]
        assert math.isclose(float(np.linalg.norm(raw["axis"])), 1.0)
        assert (raw["start_jd"], raw["end_jd"]) == (2451546.0, 2451547.0)
        assert [f["baseline_index"] for f in entry["files"]] == [0, 1]
        # Composed the way the frontend does it, the raw span is identity.
        composed = SpinBaseline(
            np.array(raw["axis"]), raw["rate_rad_s"], np.array(raw["anchor"]), 0.0
        ).compose(1e6)
        assert np.allclose(composed, _IDENTITY)

    def test_non_spinner_has_no_baselines(self) -> None:
        from space_map_data.export.position.probes.attitude.extractor import (
            ExtractionResult,
            manifest_entry,
        )
        from space_map_data.export.position.probes.attitude.segments import (
            SpinSegment,
        )
        from space_map_data.export.position.probes.attitude.writer import ChunkFile

        files = [ChunkFile("0.bin.gz", 2451545.0, 2451546.0, 10, 0)]
        entry = manifest_entry(
            ExtractionResult(10, files, [SpinSegment(0.0, D, None)], 0.0, 1.0),
            frame_name="F",
        )
        assert entry["baselines"] is None
        assert "baseline_index" not in entry["files"][0]


def test_solar_orbiter_glob_drops_only_the_yearly_dumps() -> None:
    import fnmatch
    import re

    from space_map_data.download.providers.spice.probes.attitude.patterns import (
        patterns_for,
    )

    pattern = patterns_for("SOLAR-ORBITER")[0]

    def kept(name: str) -> bool:
        assert pattern.ck_exclude_regex is not None
        return fnmatch.fnmatch(name, pattern.ck_glob) and not re.search(
            pattern.ck_exclude_regex, name
        )

    prefix = "solo_ANC_soc-flown-att_"
    for dates in (
        "20200210T000000-20210101T111121",
        "20210101T074827-20220101T175423",
        "20250101T004750-20260101T152718",
    ):
        assert not kept(f"{prefix}{dates}_V01.bc")
    for dates in (
        "20200210-20200214",
        "20201231T110809-20210101T111121",
        # Starts with the yearly dump of 2021, but ends the same day.
        "20210101T074827-20210101T212010",
        "20261029T023859-20261030T080917",
    ):
        assert kept(f"{prefix}{dates}_V01.bc")
    assert not kept(
        "solo_ANC_soc-default-att-stp_20200210-20301120_434_V1_00591_V01.bc"
    )


def test_sclk_task_reads_rows_with_date_times(tmp_path) -> None:
    from space_map_data.export.position.probes.attitude.worker import sclk_task

    path = tmp_path / "step.tsc"
    path.write_text(
        """KPL/SCLK
\\begindata
SCLK_KERNEL_ID         = ( @2026-10-26/14:56:04.15 )
SCLK_DATA_TYPE_91      = ( 1 )
SCLK01_TIME_SYSTEM_91  = ( 2 )
SCLK01_N_FIELDS_91     = ( 2 )
SCLK01_MODULI_91       = ( 4294967296 65536 )
SCLK01_OFFSETS_91      = ( 0 0 )
SCLK01_OUTPUT_DELIM_91 = ( 1 )
SCLK_PARTITION_START_91 = ( 0.0 )
SCLK_PARTITION_END_91   = ( 2.0E+14 )
SCLK01_COEFFICIENTS_91 = (
   0.0        @01-JAN-2010-00:01:06.184  1.0
   5.6623E+9  @02-JAN-2010-00:01:06.184  1.0000001 )
\\begintext
"""
    )
    rows = sclk_task(str(path))
    assert rows.shape == (2, 3)
    assert rows[1, 1] - rows[0, 1] == pytest.approx(D)
    assert rows[1, 2] == pytest.approx(1.0000001)


_TEST_FK = """\\begindata
FRAME_TEST_NADIR = -999001
FRAME_-999001_NAME = 'TEST_NADIR'
FRAME_-999001_CLASS = 5
FRAME_-999001_CLASS_ID = -999001
FRAME_-999001_CENTER = 399
FRAME_-999001_RELATIVE = 'J2000'
FRAME_-999001_DEF_STYLE = 'PARAMETERIZED'
FRAME_-999001_FAMILY = 'TWO-VECTOR'
FRAME_-999001_PRI_AXIS = 'Z'
FRAME_-999001_PRI_VECTOR_DEF = 'OBSERVER_TARGET_POSITION'
FRAME_-999001_PRI_OBSERVER = 'EARTH'
FRAME_-999001_PRI_TARGET = 'MOON'
FRAME_-999001_PRI_ABCORR = 'NONE'
FRAME_-999001_SEC_AXIS = 'X'
FRAME_-999001_SEC_VECTOR_DEF = 'CONSTANT'
FRAME_-999001_SEC_SPEC = 'RECTANGULAR'
FRAME_-999001_SEC_VECTOR = ( 1, 0, 0 )
FRAME_-999001_SEC_FRAME = 'J2000'
FRAME_-999001_SEC_ABCORR = 'NONE'
FRAME_TEST_OF_DATE = -999002
FRAME_-999002_NAME = 'TEST_OF_DATE'
FRAME_-999002_CLASS = 5
FRAME_-999002_CLASS_ID = -999002
FRAME_-999002_CENTER = 399
FRAME_-999002_RELATIVE = 'J2000'
FRAME_-999002_DEF_STYLE = 'PARAMETERIZED'
FRAME_-999002_FAMILY = 'MEAN_EQUATOR_AND_EQUINOX_OF_DATE'
FRAME_-999002_PREC_MODEL = 'EARTH_IAU_1976'
FRAME_-999002_ROTATION_STATE = 'ROTATING'
\\begintext
"""


def test_ck_needs_ephemeris_only_for_frames_that_need_positions(tmp_path) -> None:
    """A CK relative to a frame that points at the Moon needs SPKs. One
    relative to J2000, or to a dynamic frame of date like MRO's, does not."""
    import spiceypy

    from space_map_data.export.position.probes.attitude.sample import (
        ck_needs_ephemeris,
    )

    fk = tmp_path / "test.tf"
    fk.write_text(_TEST_FK)
    spiceypy.kclear()
    try:
        spiceypy.furnsh(str(fk))
        needs = {}
        for ref in ("TEST_NADIR", "TEST_OF_DATE", "J2000"):
            path = tmp_path / f"{ref}.bc"
            handle = spiceypy.ckopn(str(path), "test", 0)
            ticks = np.array([0.0, 10.0])
            spiceypy.ckw03(
                handle,
                0.0,
                10.0,
                -999000,
                ref,
                False,
                "seg",
                2,
                ticks,
                np.tile(_IDENTITY, (2, 1)),
                np.zeros((2, 3)),
                1,
                [0.0],
            )
            spiceypy.ckcls(handle)
            needs[ref] = ck_needs_ephemeris(str(path), {-999000: [(0.0, 10.0)]})
    finally:
        spiceypy.kclear()
    assert needs == {"TEST_NADIR": True, "TEST_OF_DATE": False, "J2000": False}


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
