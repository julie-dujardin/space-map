"""Per-probe orchestrator: kernel → segments → samples → keyframes → files.

This is the function the pipeline calls once per probe. SPICE must be
furnished by the caller before invocation (lsk + pck + per-mission ck +
fk + sclk); we keep furnishing out of this module so the caller can batch
multiple probes against the same generic kernels without re-furnishing.

The mission is first partitioned into rate-stable spin spans (`segments.py`):
a non-spinner is one raw span; a spinner (Juno) is one span per phase, each
with its own baseline so the adaptive sampler always keyframes a slow residual.
Each span is sampled and keyframed independently, and its chunks carry the
index of the baseline to recompose against.

Output:
  * `chunks/<chunk_idx>.bin.gz` written under `out_dir/`
  * A dict for merging into the probe's `__global__` bundle under `"attitude"`
    (see `manifest_entry`).
"""

import logging
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import spiceypy

from .adaptive import SEED_DT_S, adaptive_sample
from .keyframes import extract_keyframes
from .sample import ck_windows
from .segments import SpinSegment, plan_segments
from .writer import ChunkFile, write_chunks

logger = logging.getLogger(__name__)

# Adaptive SLERP error budget. The sweep validated 0.1° as the right
# default — visually imperceptible at planet scale, near-optimal file counts.
DEFAULT_EPS_DEG = 0.1
# Apply a spin baseline only when the turn between seed samples would alias the
# sampler. Below that, raw motion samples fine and an inverse spin only adds
# curvature; above it, a fast spinner must be baselined per phase.
ALIAS_ANGLE_RAD = math.radians(90.0)
# Cap the span handed to one `adaptive_sample` call. Its per-sample Python
# lists are ~200 B/sample, so an unbounded window (some CKs cover decades in
# one interval) at worst-case refinement density would eat GBs. Tiling only
# adds a couple of keyframes per boundary.
TILE_S = 4 * 86400.0
# Some CKs claim implausibly wide interval coverage (HUYGENS' fictional-SCLK
# CK reports one 45-year window for ~4 h of real descent data), and every
# in-gap sample costs a thrown SpiceyError ~30× a valid lookup — seed-scanning
# the claimed span would take hours. Windows longer than the threshold are
# probed at step resolution and shrunk to the runs that actually resolve,
# padded one step each side so data between probes survives.
VALIDATE_SPAN_S = 10 * 86400.0
VALIDATE_STEP_S = 3600.0

_J2000_JD = 2451545.0
_S_PER_DAY = 86400.0


@dataclass(frozen=True)
class ExtractionResult:
    """Per-probe outputs of one extraction run."""

    n_keyframes: int
    files: list[ChunkFile]
    segments: list[SpinSegment]
    coverage_start_jd: float
    coverage_end_jd: float


def _et_to_jd(et: float) -> float:
    return _J2000_JD + et / _S_PER_DAY


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
    Coverage is the union of `ck_paths`, partitioned into spin spans, then
    sampled adaptively and keyframed span-by-span to bound memory over decades.

    No coverage for `bus_instr_id` returns an empty result (n_keyframes=0) —
    it's a property of the kernel set (e.g. an impactor with no bus CK), so
    the caller caches it like any other empty extraction.
    """
    windows = ck_windows(ck_paths, bus_instr_id)
    windows = _validate_windows(frame_name, windows)
    if not windows:
        logger.info("attitude: no CK coverage for instrument %d", bus_instr_id)
        return ExtractionResult(0, write_chunks(out_dir, []), [], 0.0, 0.0)
    global_start = windows[0][0]
    global_end = max(end for _, end in windows)

    segments = plan_segments(
        frame_name,
        global_start,
        global_end,
        alias_angle=ALIAS_ANGLE_RAD,
        seed_dt=SEED_DT_S,
    )

    eps_rad = math.radians(eps_deg)
    seg_streams: list[tuple[np.ndarray, np.ndarray]] = []
    n_samples = 0
    n_gaps = 0
    for seg in segments:
        ets, quats, samples, gaps = _keyframe_segment(frame_name, seg, windows, eps_rad)
        n_samples += samples
        n_gaps += gaps
        seg_streams.append((ets, quats))

    if n_gaps:
        # CK gaps are normal for busy orbiters (MRO, Cassini); one line per probe
        # — per-file logging spammed thousands of identical warnings. The count
        # includes discarded refinement probes, so it's a gap-probe tally, not a
        # ratio of emitted samples.
        logger.warning(
            "attitude: %s — %d gap probe(s) hit CK coverage holes (repeated last good)",
            frame_name,
            n_gaps,
        )

    files = write_chunks(out_dir, seg_streams)
    # Coverage from emitted keyframes, not the CK-claimed window — kernels can
    # claim years with no resolvable data (Spitzer claims 2000, first keyframe
    # 2005) and the frontend treats this span as "attitude available".
    return ExtractionResult(
        n_keyframes=sum(len(ets) for ets, _ in seg_streams),
        files=files,
        segments=segments,
        coverage_start_jd=files[0].start_jd if files else 0.0,
        coverage_end_jd=files[-1].end_jd if files else 0.0,
    )


def _resolves(frame_name: str, et: float) -> bool:
    try:
        spiceypy.pxform("J2000", frame_name, et)
        return True
    except spiceypy.exceptions.SpiceyError:
        return False


def _validate_windows(
    frame_name: str, windows: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    """Shrink windows longer than `VALIDATE_SPAN_S` to their resolvable runs."""
    out: list[tuple[float, float]] = []
    for start, end in windows:
        if end - start <= VALIDATE_SPAN_S:
            out.append((start, end))
            continue
        ets = np.linspace(start, end, int((end - start) / VALIDATE_STEP_S) + 2)
        kept = 0.0
        run_start: float | None = None
        prev = start
        for et in ets:
            if _resolves(frame_name, float(et)):
                if run_start is None:
                    run_start = max(start, float(et) - VALIDATE_STEP_S)
                prev = float(et)
            elif run_start is not None:
                out.append((run_start, min(end, prev + VALIDATE_STEP_S)))
                kept += out[-1][1] - out[-1][0]
                run_start = None
        if run_start is not None:
            out.append((run_start, end))
            kept += end - run_start
        if kept < (end - start) - VALIDATE_STEP_S:
            logger.warning(
                "attitude: %s — CK window claims %.1f d but only %.1f d resolve; "
                "shrunk to the valid runs",
                frame_name,
                (end - start) / 86400.0,
                kept / 86400.0,
            )
    return out


def _keyframe_segment(
    frame_name: str,
    seg: SpinSegment,
    windows: list[tuple[float, float]],
    eps_rad: float,
) -> tuple[np.ndarray, np.ndarray, int, int]:
    """Adaptive-sample + keyframe one span → `(ets, quats, n_samples, n_gaps)`.

    The span's baseline residual is the stream we keyframe (raw when None). Each
    CK window is clipped to the span, then tiled to `TILE_S` so one call's
    sample stream stays bounded; `last_et` keeps the span's keyframes
    time-ascending and drops the duplicate sample at each tile boundary. The
    span's endpoints are sampled, so the boundary attitude is emitted in both
    adjacent spans' frames — the decoder never SLERPs across the baseline
    switch. Kept keyframes are copied out per tile (fancy indexing) so no
    tile's full sample array outlives its iteration.
    """
    transform = seg.baseline.residual if seg.baseline else None
    ets_parts: list[np.ndarray] = []
    quat_parts: list[np.ndarray] = []
    last_et = -math.inf
    n_samples = 0
    n_gaps = 0
    for win_start, win_end in windows:
        start = max(win_start, seg.start_et, last_et)
        end = min(win_end, seg.end_et)
        while end - start > 1.0:
            tile_end = min(end, start + TILE_S)
            ets, stream, gaps = adaptive_sample(
                frame_name, start, tile_end, eps_rad, transform=transform
            )
            n_samples += ets.size
            n_gaps += gaps
            keep = [
                i for i in extract_keyframes(stream, ets, eps_rad) if ets[i] > last_et
            ]
            if keep:
                ets_parts.append(ets[keep])
                quat_parts.append(stream[keep])
                last_et = float(ets[keep[-1]])
            start = tile_end
    if not quat_parts:
        return np.empty(0), np.empty((0, 4)), n_samples, n_gaps
    return np.concatenate(ets_parts), np.concatenate(quat_parts), n_samples, n_gaps


def _baseline_json(seg: SpinSegment) -> dict:
    """Serialise one span's baseline for the manifest `baselines` timeline."""
    b = seg.baseline
    assert b is not None
    return {
        "kind": "spin",
        "axis": [float(a) for a in b.axis],
        "rate_rad_s": float(b.rate_rad_s),
        "anchor": [float(a) for a in b.anchor],
        "anchor_jd": _et_to_jd(b.t0),
        "start_jd": _et_to_jd(seg.start_et),
        "end_jd": _et_to_jd(seg.end_et),
    }


def manifest_entry(result: ExtractionResult, *, frame_name: str) -> dict:
    """Build the `attitude` dict the writer injects into the probe's
    `__global__` object entry.

    Schema:
        {
          "frame": str,
          "start_jd": float,
          "end_jd": float,
          "n_keyframes": int,
          "baselines": [
            {"kind": "spin", "axis": [x,y,z], "rate_rad_s": float,
             "anchor": [w,x,y,z], "anchor_jd": float,
             "start_jd": float, "end_jd": float}, ...
          ] | null,
          "files": [{"name", "start_jd", "end_jd", "n_keyframes",
                     "baseline_index"?}, ...]
        }

    `baselines` is null for a non-spinner (keyframes are raw J2000→body). For a
    spinner each file's `baseline_index` selects the active span to recompose.
    """
    spinning = any(seg.baseline is not None for seg in result.segments)
    baselines = [_baseline_json(seg) for seg in result.segments] if spinning else None
    files = []
    for f in result.files:
        entry = {
            "name": f.name,
            "start_jd": f.start_jd,
            "end_jd": f.end_jd,
            "n_keyframes": f.n_keyframes,
        }
        if spinning:
            entry["baseline_index"] = f.baseline_index
        files.append(entry)
    return {
        "frame": frame_name,
        "start_jd": result.coverage_start_jd,
        "end_jd": result.coverage_end_jd,
        "n_keyframes": result.n_keyframes,
        "baselines": baselines,
        "files": files,
    }
