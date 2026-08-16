"""Pack keyframes into gzipped chunk files and produce the per-probe manifest.

One probe → many `.bin.gz` files under `v1/attitude/<probe-id>/<N>.bin.gz`,
plus a manifest entry for the probe's `__global__` object bundle. The chunker
walks keyframes serially, starting a new file when the raw byte budget would
overflow `TARGET_RAW_BYTES` — working from a raw target keeps the pack loop
allocation-free; gzip applies once per chunk at close.

Writes are atomic via `.part` rename so a crashed export leaves the old
chunk in place.
"""

import gzip
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

# Per-file raw payload budget. 250 KB raw lands at ~100–200 KB gzipped for
# the attitude streams the benchmark covered. Above that, file-loading
# latency starts to bite on first-focus. Below it, the per-probe file
# count grows past a few dozen for active orbiters.
TARGET_RAW_BYTES = 250 * 1024

_J2000_JD = 2451545.0
_S_PER_DAY = 86400.0


@dataclass(frozen=True)
class ChunkFile:
    """Metadata for one written chunk file — used to build the manifest."""

    name: str  # "0.bin.gz", "1.bin.gz", ...
    start_jd: float
    end_jd: float
    n_keyframes: int
    baseline_index: int  # which spin span this chunk's residual recomposes against


def _smallest_three(q: np.ndarray) -> tuple[int, int, int, int]:
    """Pack one quaternion as (idx_dropped, a, b, c) int16-quantised. The
    largest |component| is dropped and reconstructed via
    `sqrt(1 - a² - b² - c²)`; sign is canonicalised so it's positive,
    avoiding ± ambiguity from the sqrt.
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
    segments: list[tuple[np.ndarray, np.ndarray]],
) -> list[ChunkFile]:
    """Write `<N>.bin.gz` files into `out_dir`, return per-file metadata.

    `segments` is one `(ets, quats)` keyframe stream per spin span, in span
    order — chunks are numbered globally but never straddle a span, each
    carrying the span's index as `baseline_index`. Replaces any existing
    `*.bin.gz` so stale chunks can't outlive a content change.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.bin.gz"):
        stale.unlink()

    files: list[ChunkFile] = []
    chunk_idx = 0
    for baseline_index, (ets, quats) in enumerate(segments):
        n = len(ets)
        start = 0
        while start < n:
            # Walk forward until we'd overflow the raw budget. Always keep at
            # least one keyframe per file (a single 11 B keyframe can't overflow,
            # but the invariant is cheap to hold).
            end = start + 1
            budget = HEADER_SIZE + KEYFRAME_SIZE
            while end < n and budget + KEYFRAME_SIZE <= TARGET_RAW_BYTES:
                budget += KEYFRAME_SIZE
                end += 1
            files.append(
                _write_one_chunk(
                    out_dir, chunk_idx, quats, ets, start, end, baseline_index
                )
            )
            chunk_idx += 1
            start = end
    return files


def _write_one_chunk(
    out_dir: Path,
    chunk_idx: int,
    quats: np.ndarray,
    ets: np.ndarray,
    start: int,
    end: int,
    baseline_index: int,
) -> ChunkFile:
    """Pack + gzip + atomic-write a single chunk file covering `ets[start:end]`."""
    start_jd = _et_to_jd(float(ets[start]))
    end_jd = _et_to_jd(float(ets[end - 1]))

    raw = bytearray(pack_header(start_jd))
    prev_et = float(ets[start])
    for k in range(start, end):
        et = float(ets[k])
        # First keyframe has dt=0; subsequent ones are inter-keyframe deltas.
        # float32 keeps sub-second spacing — integer seconds drifted the
        # accumulated timeline by minutes across a dense chunk.
        dt = 0.0 if k == start else max(0.0, et - prev_et)
        idx_three, a, b, c = _smallest_three(quats[k])
        raw.extend(pack_keyframe(dt, idx_three, a, b, c))
        prev_et = et

    payload = gzip.compress(bytes(raw), compresslevel=6)
    name = f"{chunk_idx}.bin.gz"
    dest = out_dir / name
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(payload)
    os.replace(tmp, dest)

    return ChunkFile(
        name=name,
        start_jd=start_jd,
        end_jd=end_jd,
        n_keyframes=end - start,
        baseline_index=baseline_index,
    )
