"""Assemble cached CSVs into a multi-segment SPK13 binary."""

import logging
from pathlib import Path

import numpy as np
import orjson
import spiceypy

from .horizons_api import Sample, _parse_chunks
from .layout import SYNTH_CACHE_ROOT, SYNTH_KERNELS_DIR

logger = logging.getLogger(__name__)


def _write_segment(
    handle: int,
    naif_id: int,
    samples: list[Sample],
    segid: str,
    *,
    degree: int = 7,
) -> bool:
    if len(samples) < degree + 1:
        logger.warning(
            "naif %d seg '%s': %d samples below degree+1=%d, skipping",
            naif_id,
            segid,
            len(samples),
            degree + 1,
        )
        return False
    states = np.asarray([s.state for s in samples], dtype=float)
    epochs = np.asarray([s.et for s in samples], dtype=float)
    spiceypy.spkw13(
        handle,
        naif_id,
        0,
        "J2000",
        float(epochs[0]),
        float(epochs[-1]),
        segid[:40],
        degree,
        len(samples),
        states,
        epochs,
    )
    return True


def _sample_runs(
    samples: list[Sample], exclude: list[tuple[float, float]]
) -> list[list[Sample]]:
    """Split `samples` into runs of consecutive samples outside `exclude`.

    Each run becomes its own segment — a single segment spanning a carved-out
    hole would claim coverage there and interpolate garbage across it.
    """
    if not exclude:
        return [samples]
    runs: list[list[Sample]] = []
    cur: list[Sample] = []
    for s in samples:
        if any(start <= s.et <= end for start, end in exclude):
            if cur:
                runs.append(cur)
                cur = []
        else:
            cur.append(s)
    if cur:
        runs.append(cur)
    return runs


def build_one(naif_id: int, exclude: list[tuple[float, float]] | None = None) -> Path:
    """Assemble cached CSVs into a single multi-segment SPK13.

    Coarse segment first, then refined segments — SPICE evaluates with the
    last matching segment in the file winning for overlapping epochs, so
    queries inside a refinement window automatically use the 1h data.

    `exclude` carves out ET intervals (agency-SPK coverage) so the synth only
    claims the complement; raises like an empty build when nothing survives.

    Writes to `<spk>.tmp` then atomically replaces `<spk>` so a concurrent
    reader (e.g. an in-flight `space-map-export` furnshing the same file)
    keeps its already-open fd on the previous inode and finishes cleanly.
    Without this the export raced and crashed with SPICE(FILENOTFOUND) when
    the downloader unlinked an SPK between the export's furnsh and unload.
    """
    cache_dir = SYNTH_CACHE_ROOT / str(naif_id)
    meta = orjson.loads((cache_dir / "meta.json").read_bytes())
    SYNTH_KERNELS_DIR.mkdir(parents=True, exist_ok=True)
    spk_path = SYNTH_KERNELS_DIR / f"{naif_id}.bsp"
    tmp_path = spk_path.with_suffix(spk_path.suffix + ".tmp")
    if tmp_path.exists():
        tmp_path.unlink()

    handle = spiceypy.spkopn(str(tmp_path), f"Horizons synth {meta['name']}"[:60], 0)
    written = 0

    def write_runs(samples: list[Sample], segid: str) -> int:
        n = 0
        for j, run in enumerate(_sample_runs(samples, exclude or [])):
            sid = segid if j == 0 else f"{segid}~{j}"
            if _write_segment(handle, naif_id, run, sid):
                n += 1
        return n

    try:
        coarse_samples = _parse_chunks((cache_dir / meta["coarse"]["file"]).read_text())
        written += write_runs(coarse_samples, f"coarse_{meta['revised']}")
        for r in meta["refined"]:
            # `_parse_chunks` handles multi-block CSVs from `_fetch_vectors_chunked`
            # (for tight-cadence refines too big to fit in one request) while still
            # working on legacy single-block 1-h CSVs.
            samples = _parse_chunks((cache_dir / r["file"]).read_text())
            written += write_runs(samples, f"refine_{r['start']}_{r['end']}")
    finally:
        spiceypy.spkcls(handle)

    if written == 0:
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError(f"naif {naif_id}: no usable segments")
    tmp_path.replace(spk_path)

    logger.info(
        "naif %d: wrote %s (%d segments, %d bytes)",
        naif_id,
        spk_path.name,
        written,
        spk_path.stat().st_size,
    )
    return spk_path
