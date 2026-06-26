"""Unit tests for the attitude extraction stack.

Focused on the pieces that don't need furnished kernels — wire format,
quaternion utilities, keyframe extraction on synthetic streams, baseline
spin fit. The end-to-end smoke against MRO lives in
`scripts/probe_orientation_smoke.py` because it needs the cached
benchmark CK.
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
    # Max-ish int16 components + a sub-second dt — float32 must keep the
    # fractional spacing that integer seconds dropped.
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
    # SLERP between two points spanning 1000° goes the *short way* — so the
    # walker has to chunk at least every ~180° to avoid wrap-around. ~6
    # keyframes is plenty; we accept up to 20 for slack.
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
    # Axis can be sign-flipped; rate magnitude must match.
    # Tolerance reflects central-difference numerical error at this sample
    # density — central diff is O((dt)²) and we're sampling at 50 Hz.
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
        orchestrator._run_probe(
            out_dir,
            {"probe_id": 7, "kernel_sources": [{"mission": "M", "naif_id": -82}]},
            "M",
            "FRAME",
            ["/ck/a.bc"],
            stamps,
            global_data,
            summary,
        )
        return global_data, summary

    def test_second_run_skips_extraction(self, monkeypatch, tmp_path) -> None:
        calls: list[int] = []
        stamps = {"/ck/a.bc": {"mtime_ns": 1, "size": 2}}
        gd1, s1 = self._run(monkeypatch, tmp_path, stamps, calls)
        gd2, s2 = self._run(monkeypatch, tmp_path, stamps, calls)
        assert len(calls) == 1  # second run served from cache
        assert s2["7"]["cached"] is True
        # Manifest re-injected on the cache hit even though nothing re-extracted.
        assert gd1["probe-7"]["attitude"] == gd2["probe-7"]["attitude"]
        assert gd2["probe-7"]["attitude"]["n_keyframes"] == 10

    def test_kernel_change_reextracts(self, monkeypatch, tmp_path) -> None:
        calls: list[int] = []
        self._run(
            monkeypatch, tmp_path, {"/ck/a.bc": {"mtime_ns": 1, "size": 2}}, calls
        )
        self._run(
            monkeypatch, tmp_path, {"/ck/a.bc": {"mtime_ns": 9, "size": 2}}, calls
        )
        assert len(calls) == 2  # changed stamp invalidated the cache

    def test_missing_chunk_invalidates_cache(self, monkeypatch, tmp_path) -> None:
        calls: list[int] = []
        stamps = {"/ck/a.bc": {"mtime_ns": 1, "size": 2}}
        self._run(monkeypatch, tmp_path, stamps, calls)
        (tmp_path / "attitude" / "7" / "0.bin.gz").unlink()
        self._run(monkeypatch, tmp_path, stamps, calls)
        assert len(calls) == 2  # vanished chunk forces a rebuild


def test_enforce_min_span_drops_slivers() -> None:
    """Boundaries closer than the min span (to each other or the ends) are
    dropped so a brief blip can't carve a sliver segment."""
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
