"""Per-probe orchestrator: kernel → samples → keyframes → files + manifest.

This is the function the pipeline calls once per probe. SPICE must be
furnished by the caller before invocation (lsk + pck + per-mission ck +
fk + sclk); we keep furnishing out of this module so the caller can batch
multiple probes against the same generic kernels without re-furnishing.

Output:
  * `chunks/<chunk_idx>.bin.gz` written under `out_dir/`
  * A dict suitable for merging into the probe's `__global__` object
    bundle entry under the `"attitude"` key (see `manifest_entry` below).
"""

import logging
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .adaptive import SEED_DT_S, adaptive_sample
from .baseline import baseline_quaternion, fit_spin_baseline
from .keyframes import extract_keyframes
from .quaternion import angle_between, q_conj, q_mul
from .sample import ck_windows, sample_truth
from .writer import ChunkFile, write_chunks

logger = logging.getLogger(__name__)

# Adaptive SLERP error budget. The sweep validated 0.1° as the right
# default — visually imperceptible at planet scale, near-optimal file
# counts (a single knob; phase classifier added overhead without payoff).
DEFAULT_EPS_DEG = 0.1

# Spin fit: dense 10 Hz over a bounded leading window, so a fast spin is
# resolved even when the first CK file is months long.
SAMPLE_HZ = 10.0
FIT_WINDOW_S = 2 * 86400.0
FIT_MAX_SAMPLES = 50_000
# Apply the spin baseline only when the turn between seed samples would alias
# the sampler. Below that, raw motion samples fine and the inverse-spin
# residual only adds curvature (a slow ditherer samples worse, not better).
ALIAS_ANGLE_RAD = math.radians(90.0)


def _grid_n(duration_s: float, cap: int) -> int:
    """Sample count for a window: 10 Hz, clamped to [2, cap]."""
    return int(max(2, min(cap, round(duration_s * SAMPLE_HZ))))


def _residual_transform(axis, rate, anchor, t0):
    """Map raw J2000->body truth → spin-baseline residual q_baseline(t)⁻¹·q."""

    def transform(et: float, q: np.ndarray) -> np.ndarray:
        b = q_mul(baseline_quaternion(axis, rate, et - t0), anchor)
        return q_mul(q_conj(b), q)

    return transform


def _persistent_spin_speed(frame_name: str, t0: float, t1: float) -> float:
    """Median local angular speed (rad/s) sampled across the whole mission.

    Close pxform pairs measure the true instantaneous rate without the aliasing
    a coarse single-spacing estimate suffers. Distinguishes a persistent spinner
    (Juno) from a transient early detumble (Europa Clipper) that a lead-window
    fit alone reads as a global spin.
    """
    n, ddt = 96, 1.0
    starts = np.linspace(t0, max(t0, t1 - ddt), n)
    ets = np.empty(2 * n)
    ets[0::2] = starts
    ets[1::2] = starts + ddt
    q = sample_truth(frame_name, ets)
    speeds = [angle_between(q[2 * i], q[2 * i + 1]) / ddt for i in range(n)]
    return float(np.median(speeds))


@dataclass(frozen=True)
class ExtractionResult:
    """Per-probe outputs of one extraction run."""

    n_keyframes: int
    files: list[ChunkFile]
    baseline_axis: list[float] | None
    baseline_rate_rad_s: float | None
    baseline_anchor: list[float] | None
    coverage_start_jd: float
    coverage_end_jd: float


_J2000_JD = 2451545.0
_S_PER_DAY = 86400.0


def extract_attitude(
    out_dir: Path,
    ck_paths: list[str],
    bus_instr_id: int,
    frame_name: str,
    *,
    eps_deg: float = DEFAULT_EPS_DEG,
) -> ExtractionResult:
    """Extract attitude for one probe and write its chunk files.

    Caller furnishes kernels. `bus_instr_id` is the CK instrument ID
    (typically `naif_id × 1000`) for the spacecraft bus frame; `frame_name`
    is the FK-registered name resolvable by `pxform("J2000", frame_name, et)`.
    Coverage is the union of `ck_paths`, sampled adaptively and keyframed
    file-by-file to bound memory over decades.

    The spin baseline is fit unconditionally and applied iff its residual is
    angularly tighter than the raw stream — a fast spinner (Juno, LADEE) must
    be baselined so the adaptive sampler doesn't alias its turns.
    """
    windows = ck_windows(ck_paths, bus_instr_id)
    if not windows:
        raise ValueError(f"no CK coverage for instrument {bus_instr_id}")
    global_start = windows[0][0]
    global_end = max(end for _, end in windows)

    # Fit the spin from a dense, duration-bounded leading window.
    fit_start = global_start
    fit_end = min(windows[0][1], fit_start + FIT_WINDOW_S)
    fit_ets = np.linspace(
        fit_start, fit_end, _grid_n(fit_end - fit_start, FIT_MAX_SAMPLES)
    )
    axis, rate, anchor = fit_spin_baseline(sample_truth(frame_name, fit_ets), fit_ets)

    # Baseline only a persistent fast spinner (Juno): a turn wider than the
    # alias angle per seed aliases the raw sampler. Gate on the whole-mission
    # median speed, not the lead-window fit — else a transient early detumble
    # (Europa Clipper) baselines the entire mission with a wrong inverse spin.
    spin_speed = _persistent_spin_speed(frame_name, global_start, global_end)
    use_baseline = spin_speed * SEED_DT_S > ALIAS_ANGLE_RAD
    transform = (
        _residual_transform(axis, rate, anchor, global_start) if use_baseline else None
    )

    # Per file: adaptive-sample the stream (raw or residual), decimate to
    # keyframes, accumulate. Overlap is trimmed against the last emitted
    # keyframe to keep the merge time-ascending.
    eps_rad = math.radians(eps_deg)
    kf_quats: list[np.ndarray] = []
    kf_ets: list[float] = []
    last_et = -math.inf
    n_samples = 0
    n_gaps = 0
    for start_et, end_et in windows:
        seg_start = max(start_et, last_et)
        if end_et - seg_start <= 1.0:
            continue
        ets, stream, gaps = adaptive_sample(
            frame_name, seg_start, end_et, eps_rad, transform=transform
        )
        n_samples += ets.size
        n_gaps += gaps
        for i in extract_keyframes(stream, ets, eps_rad):
            t = float(ets[i])
            if t <= last_et:
                continue
            kf_ets.append(t)
            kf_quats.append(stream[i])
            last_et = t

    if n_gaps:
        # One line per probe — CK gaps are normal for busy orbiters (MRO,
        # Cassini); per-file logging spammed thousands of identical warnings.
        logger.warning(
            "attitude: %s — %d/%d samples in CK gaps (repeated last good)",
            frame_name,
            n_gaps,
            n_samples,
        )

    quats = np.array(kf_quats) if kf_quats else np.empty((0, 4))
    ets_arr = np.array(kf_ets)
    files = write_chunks(out_dir, quats, ets_arr, list(range(len(kf_quats))))

    return ExtractionResult(
        n_keyframes=len(kf_quats),
        files=files,
        baseline_axis=[float(a) for a in axis] if use_baseline else None,
        baseline_rate_rad_s=float(rate) if use_baseline else None,
        baseline_anchor=[float(a) for a in anchor] if use_baseline else None,
        coverage_start_jd=_J2000_JD + global_start / _S_PER_DAY,
        coverage_end_jd=_J2000_JD + global_end / _S_PER_DAY,
    )


def manifest_entry(result: ExtractionResult, *, frame_name: str) -> dict:
    """Build the `attitude` dict the writer injects into the probe's
    `__global__` object entry.

    Schema:
        {
          "frame": str,
          "start_jd": float,
          "end_jd": float,
          "n_keyframes": int,
          "baseline": {
            "kind": "spin",
            "axis": [x, y, z],
            "rate_rad_s": float,
            "anchor": [w, x, y, z]
          } | null,
          "files": [{"name": "0.bin.gz", "start_jd": ..., "end_jd": ..., "n_keyframes": ...}, ...]
        }
    """
    baseline: dict | None = None
    if result.baseline_axis is not None:
        baseline = {
            "kind": "spin",
            "axis": result.baseline_axis,
            "rate_rad_s": result.baseline_rate_rad_s,
            "anchor": result.baseline_anchor,
        }
    return {
        "frame": frame_name,
        "start_jd": result.coverage_start_jd,
        "end_jd": result.coverage_end_jd,
        "n_keyframes": result.n_keyframes,
        "baseline": baseline,
        "files": [
            {
                "name": f.name,
                "start_jd": f.start_jd,
                "end_jd": f.end_jd,
                "n_keyframes": f.n_keyframes,
            }
            for f in result.files
        ],
    }
