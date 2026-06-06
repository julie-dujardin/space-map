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
    apply_baseline,
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
    # Max-ish positive and negative int16 components + max uint32 dt — the
    # ranges that quantise/dequantise must survive without overflow.
    kf = pack_keyframe(
        dt_seconds=4_000_000_000,
        idx=3,
        a=COMPONENT_SCALE,
        b=-COMPONENT_SCALE,
        c=0,
    )
    assert len(kf) == KEYFRAME_SIZE
    dt, idx, a, b, c = unpack_keyframe(kf, 0)
    assert dt == 4_000_000_000
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
    axis, rate, anchor = fit_spin_baseline(quats, ets)
    # Axis can be sign-flipped; rate magnitude must match.
    # Tolerance reflects central-difference numerical error at this sample
    # density — central diff is O((dt)²) and we're sampling at 50 Hz.
    assert abs(rate - rate_true) < 1e-4
    assert np.allclose(np.abs(axis), np.abs(axis_true), atol=1e-4)
    assert np.allclose(anchor, quats[0])


def test_apply_baseline_residual_is_identity_for_pure_spin() -> None:
    """If truth is exactly a constant-rate spin, baseline subtraction
    should collapse it to a stream of identity quaternions."""
    n = 500
    ets = np.linspace(0.0, 10.0, n)
    rate = math.radians(30.0)
    quats = np.empty((n, 4))
    for i, et in enumerate(ets):
        half = rate * et / 2.0
        quats[i] = [math.cos(half), 0.0, 0.0, math.sin(half)]
    axis, rate_fit, anchor = fit_spin_baseline(quats, ets)
    residual = apply_baseline(quats, ets, axis, rate_fit, anchor)
    # Every residual should be near identity (≤ 0.001 rad).
    for r in residual:
        assert angle_between(r, _IDENTITY) < 1e-3
