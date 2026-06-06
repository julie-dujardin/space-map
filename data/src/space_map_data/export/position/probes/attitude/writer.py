"""Pack keyframes into gzipped chunk files and produce the per-probe manifest.

One probe → many ~200 KB `.bin.gz` files under
`v1/attitude/<probe-id>/<N>.bin.gz`, plus a manifest entry merged into
the probe's `__global__` object bundle.

The chunker walks keyframes serially, accumulates raw bytes, and starts a
new file when the running raw budget would overflow `TARGET_RAW_BYTES`.
Working from a raw target instead of a compressed one keeps the pack
loop allocation-free; gzip is applied once per chunk at close time, and
the resulting compressed file sizes land in the 100 – 250 KB band for
attitude streams we benchmarked.

File writes are atomic via `.part` rename so a crashed export leaves the
old chunk in place — the next run repacks whichever chunks changed.
"""

import gzip
import logging
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .format import (
    HEADER_SIZE,
    KEYFRAME_SIZE,
    pack_header,
    pack_keyframe,
    quantise_component,
)

logger = logging.getLogger(__name__)

# Per-file raw payload budget. 250 KB raw lands at ~100–200 KB gzipped for
# the attitude streams the benchmark covered. Above that, file-loading
# latency starts to bite on first-focus. Below it, the per-probe file
# count grows past a few dozen for active orbiters.
TARGET_RAW_BYTES = 250 * 1024

_J2000_JD = 2451545.0
_S_PER_DAY = 86400.0
_DT_MAX = 0xFFFF_FFFF  # uint32 ceiling — ~136 years


@dataclass(frozen=True)
class ChunkFile:
    """Metadata for one written chunk file — used to build the manifest."""

    name: str  # "0.bin.gz", "1.bin.gz", ...
    start_jd: float
    end_jd: float
    n_keyframes: int


def _smallest_three(q: np.ndarray) -> tuple[int, int, int, int]:
    """Pack one quaternion as (idx_dropped, a, b, c) int16-quantised.

    The largest |component| is dropped and reconstructed at decode time
    via `sqrt(1 - a² - b² - c²)`. Sign is canonicalised so the dropped
    component is positive — that way the reconstruction has a unique
    answer (no ± ambiguity from the sqrt).
    """
    idx = int(np.argmax(np.abs(q)))
    if q[idx] < 0:
        q = -q
    others = [q[j] for j in range(4) if j != idx]
    return (
        idx,
        quantise_component(float(others[0])),
        quantise_component(float(others[1])),
        quantise_component(float(others[2])),
    )


def _et_to_jd(et: float) -> float:
    return _J2000_JD + et / _S_PER_DAY


def write_chunks(
    out_dir: Path,
    quats: np.ndarray,
    ets: np.ndarray,
    keyframe_indices: list[int],
) -> list[ChunkFile]:
    """Write `<N>.bin.gz` files into `out_dir`, return per-file metadata.

    Replaces any existing `*.bin.gz` in `out_dir` — repack is wholesale
    so stale chunks can't outlive a content change in the keyframe list.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.bin.gz"):
        stale.unlink()

    if not keyframe_indices:
        return []

    files: list[ChunkFile] = []
    chunk_idx = 0
    file_start_idx = 0
    raw_budget = HEADER_SIZE
    while file_start_idx < len(keyframe_indices):
        # Walk forward until we'd overflow the raw budget. Always keep at
        # least one keyframe per file even if a single keyframe somehow
        # exceeds the budget (it can't with our 11 B fixed width, but the
        # invariant is cheap to maintain).
        end_idx = file_start_idx + 1
        budget = raw_budget + KEYFRAME_SIZE
        while (
            end_idx < len(keyframe_indices)
            and budget + KEYFRAME_SIZE <= TARGET_RAW_BYTES
        ):
            budget += KEYFRAME_SIZE
            end_idx += 1

        file_meta = _write_one_chunk(
            out_dir, chunk_idx, quats, ets, keyframe_indices, file_start_idx, end_idx
        )
        files.append(file_meta)
        chunk_idx += 1
        file_start_idx = end_idx
        raw_budget = HEADER_SIZE

    return files


def _write_one_chunk(
    out_dir: Path,
    chunk_idx: int,
    quats: np.ndarray,
    ets: np.ndarray,
    keyframe_indices: list[int],
    file_start_idx: int,
    file_end_idx: int,
) -> ChunkFile:
    """Pack + gzip + atomic-write a single chunk file."""
    sample_indices = keyframe_indices[file_start_idx:file_end_idx]
    first_idx = sample_indices[0]
    last_idx = sample_indices[-1]
    start_jd = _et_to_jd(float(ets[first_idx]))
    end_jd = _et_to_jd(float(ets[last_idx]))

    raw = bytearray(pack_header(start_jd))
    prev_et = float(ets[first_idx])
    for k, idx in enumerate(sample_indices):
        et = float(ets[idx])
        # First keyframe has dt=0; subsequent ones are inter-keyframe deltas.
        dt = 0 if k == 0 else max(0, round(et - prev_et))
        if dt > _DT_MAX:
            # Should never happen under our adaptive-keyframe budget (max
            # gap is bounded by the SLERP error budget over the CK window),
            # but the format is finite. Cap and log so the symptom shows.
            logger.warning("attitude keyframe dt %d s exceeds uint32 cap, clamping", dt)
            dt = _DT_MAX
        idx_three, a, b, c = _smallest_three(quats[idx])
        raw.extend(pack_keyframe(dt, idx_three, a, b, c))
        prev_et = et

    payload = gzip.compress(bytes(raw), compresslevel=6)
    name = f"{chunk_idx}.bin.gz"
    dest = out_dir / name
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(payload)
    os.replace(tmp, dest)

    return ChunkFile(
        name=name, start_jd=start_jd, end_jd=end_jd, n_keyframes=len(sample_indices)
    )
