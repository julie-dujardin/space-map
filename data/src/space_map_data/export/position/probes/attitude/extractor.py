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

from .baseline import (
    apply_baseline,
    fit_spin_baseline,
    stream_p95_angle_from_identity,
)
from .keyframes import extract_keyframes
from .sample import ck_coverage, sample_truth
from .writer import ChunkFile, write_chunks

logger = logging.getLogger(__name__)

# Adaptive SLERP error budget. The sweep validated 0.1° as the right
# default — visually imperceptible at planet scale, near-optimal file
# counts (a single knob; phase classifier added overhead without payoff).
DEFAULT_EPS_DEG = 0.1

# Sampling cadence (Hz). 10 Hz is dense enough to capture HiRISE-class
# slews; the adaptive keyframe extractor discards the redundancy after
# fitting. Capped sample count keeps wall time bounded on multi-year CKs.
SAMPLE_HZ = 10.0
MAX_SAMPLES = 1_000_000


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
    ck_path: str,
    bus_instr_id: int,
    frame_name: str,
    *,
    eps_deg: float = DEFAULT_EPS_DEG,
) -> ExtractionResult:
    """Extract attitude for one probe and write its chunk files.

    Caller furnishes kernels. `bus_instr_id` is the CK instrument ID
    (typically `naif_id × 1000`) for the spacecraft bus frame; `frame_name`
    is the FK-registered name resolvable by `pxform("J2000", frame_name, et)`.

    The spin baseline is fit unconditionally and applied iff the residual
    is angularly tighter than the raw stream — that test is the one we
    validated across the sweep (Juno + 11 of 14 missions triggered it).
    """
    start_et, end_et = ck_coverage(ck_path, bus_instr_id)
    coverage_s = end_et - start_et
    n_samples = max(2, min(MAX_SAMPLES, int(coverage_s * SAMPLE_HZ)))
    ets = np.linspace(start_et, end_et, n_samples)
    truth = sample_truth(frame_name, ets)

    # Always fit, conditionally apply. The decision lives here so the
    # writer can mirror the decoder exactly (manifest carries baseline iff
    # we shipped a residual stream).
    axis, rate, anchor = fit_spin_baseline(truth, ets)
    residual = apply_baseline(truth, ets, axis, rate, anchor)
    truth_p95 = stream_p95_angle_from_identity(truth)
    resid_p95 = stream_p95_angle_from_identity(residual)
    use_baseline = resid_p95 < truth_p95

    stream = residual if use_baseline else truth
    eps_rad = math.radians(eps_deg)
    kf_indices = extract_keyframes(stream, ets, eps_rad)
    files = write_chunks(out_dir, stream, ets, kf_indices)

    return ExtractionResult(
        n_keyframes=len(kf_indices),
        files=files,
        baseline_axis=[float(a) for a in axis] if use_baseline else None,
        baseline_rate_rad_s=float(rate) if use_baseline else None,
        baseline_anchor=[float(a) for a in anchor] if use_baseline else None,
        coverage_start_jd=_J2000_JD + start_et / _S_PER_DAY,
        coverage_end_jd=_J2000_JD + end_et / _S_PER_DAY,
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
