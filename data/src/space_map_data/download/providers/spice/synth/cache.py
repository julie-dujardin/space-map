"""Cache-aware fetch loop: probe → coarse → auto-refine → meta.json."""

import logging
from datetime import datetime, timezone

import httpx
import numpy as np
import orjson
import spiceypy

from .horizons_api import (
    _fetch_vectors_chunked,
    _parse_chunks,
    detect_window,
    fetch_obj_data,
)
from .layout import SYNTH_CACHE_ROOT
from .refine import (
    _coarse_step_for,
    _furnish_planets,
    _identify_refinement_windows,
    _refine_step_for,
    compute_major_body_hill_km,
)

logger = logging.getLogger(__name__)


def fetch_one(client: httpx.Client, naif_id: int, *, force: bool = False) -> dict:
    """Probe + fetch coarse + auto-refine → write cache. Returns meta dict.

    Cache layout:
      {SYNTH_CACHE_ROOT}/{naif_id}/meta.json
      {SYNTH_CACHE_ROOT}/{naif_id}/coarse_{start}_{end}_7d.csv
      {SYNTH_CACHE_ROOT}/{naif_id}/refine_{start}_{end}_1h.csv  (per window)

    Skip rule: if `meta.json` already records the current Horizons `Revised :`
    date, all subsequent network work is suppressed.
    """
    cache_dir = SYNTH_CACHE_ROOT / str(naif_id)
    cache_dir.mkdir(parents=True, exist_ok=True)
    meta_path = cache_dir / "meta.json"

    obj = fetch_obj_data(client, naif_id)
    logger.info("naif %d → %s (revised %s)", naif_id, obj.name, obj.revised)

    if not force and meta_path.exists():
        prev = orjson.loads(meta_path.read_bytes())
        expected_tag = _refine_step_for(naif_id).replace(" ", "")
        cached_tags = {r.get("cadence") for r in prev.get("refined", [])}
        cadence_match = not cached_tags or cached_tags == {expected_tag}
        if prev.get("revised") == obj.revised and cadence_match:
            logger.info(
                "naif %d: cache up to date (revised %s), skipping fetch",
                naif_id,
                obj.revised,
            )
            return prev
        if not cadence_match:
            logger.info(
                "naif %d: cached refine cadence %s != expected %s; refetching",
                naif_id,
                ",".join(sorted(t for t in cached_tags if t)) or "(none)",
                expected_tag,
            )

    win_start, win_end = detect_window(client, naif_id)
    span_days = (
        datetime.fromisoformat(win_end).date()
        - datetime.fromisoformat(win_start).date()
    ).days
    coarse_step = _coarse_step_for(span_days)
    skip_refine = coarse_step == "1 h"
    logger.info(
        "naif %d window: %s → %s (%dd, coarse=%s%s)",
        naif_id,
        win_start,
        win_end,
        span_days,
        coarse_step,
        "; refinement skipped" if skip_refine else "",
    )

    coarse_tag = coarse_step.replace(" ", "")
    coarse_name = f"coarse_{win_start}_{win_end}_{coarse_tag}.csv"
    coarse_path = cache_dir / coarse_name
    coarse_text = _fetch_vectors_chunked(
        client, naif_id, win_start, win_end, coarse_step
    )
    coarse_path.write_text(coarse_text)
    coarse_samples = _parse_chunks(coarse_text)
    logger.info("naif %d: coarse %d samples", naif_id, len(coarse_samples))

    refine_meta: list[dict] = []
    if coarse_samples and not skip_refine:
        furnished = _furnish_planets()
        try:

            def get_pos(body_id: int, et: float) -> np.ndarray:
                pos, _ = spiceypy.spkpos(str(body_id), et, "J2000", "NONE", "0")
                return pos

            windows = _identify_refinement_windows(
                coarse_samples,
                get_pos,
                coverage_start_iso=win_start,
                coverage_end_iso=win_end,
                hill_table=compute_major_body_hill_km(),
            )
        finally:
            for p in furnished:
                spiceypy.unload(str(p))

        refine_step = _refine_step_for(naif_id)
        refine_tag = refine_step.replace(" ", "")
        logger.info(
            "naif %d: %d refinement windows @ %s",
            naif_id,
            len(windows),
            refine_step,
        )
        for ws, we in windows:
            fn = f"refine_{ws}_{we}_{refine_tag}.csv"
            path = cache_dir / fn
            logger.info("naif %d: refining %s..%s @ %s", naif_id, ws, we, refine_step)
            try:
                text = _fetch_vectors_chunked(client, naif_id, ws, we, refine_step)
            except httpx.HTTPError as exc:
                logger.warning("naif %d refine %s..%s failed: %s", naif_id, ws, we, exc)
                continue
            path.write_text(text)
            samples = _parse_chunks(text)
            refine_meta.append(
                {
                    "start": ws,
                    "end": we,
                    "cadence": refine_tag,
                    "file": fn,
                    "count": len(samples),
                }
            )

    meta = {
        "naif_id": naif_id,
        "name": obj.name,
        "revised": obj.revised,
        "window_start": win_start,
        "window_end": win_end,
        "last_fetch": datetime.now(timezone.utc).isoformat(),
        "coarse": {
            "file": coarse_name,
            "cadence": coarse_tag,
            "count": len(coarse_samples),
        },
        "refined": refine_meta,
    }
    meta_path.write_bytes(orjson.dumps(meta, option=orjson.OPT_INDENT_2))
    return meta
