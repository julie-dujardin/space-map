"""Probe-export coverage slicers anchored at `PROBE_EXPORT_START_YEAR`."""

import math

from space_map_data.utils.time import S_PER_DAY, jd_to_et

# 2150 sits past every predicted-ephemeris kernel (Voyager VIM → ~2120), so
# `chunks` in the manifest is an upper bound on the max emitted chunk index.
PROBE_EXPORT_START_YEAR = 1950
PROBE_EXPORT_END_YEAR = 2150


def landed_chunk_range(
    chunk_days: float,
    t_start_et: float,
    t_end_et: float,
    start_jd_anchor: float,
) -> list[tuple[int, float, float]]:
    """Slice a landed phase across streaming chunks; does NOT snap to the
    sub-chunk grid (landed records carry their own ET offsets)."""
    chunk_s = chunk_days * S_PER_DAY
    start_et_anchor = jd_to_et(start_jd_anchor)
    first_idx = int(math.floor((t_start_et - start_et_anchor) / chunk_s))
    last_idx = int(math.ceil((t_end_et - start_et_anchor) / chunk_s))
    out: list[tuple[int, float, float]] = []
    for idx in range(first_idx, last_idx):
        cs = start_et_anchor + idx * chunk_s
        ce = cs + chunk_s
        s = max(cs, t_start_et)
        e = min(ce, t_end_et)
        if e <= s:
            continue
        out.append((idx, s, e))
    return out


def chunk_aligned_range(
    chunk_days: float,
    subchunk_days: float,
    t_start_et: float,
    t_end_et: float,
    start_jd_anchor: float,
) -> list[tuple[int, float, float]]:
    """Return `[(chunk_idx, sub_t_start_et, sub_t_end_et), ...]` covering
    `[t_start_et, t_end_et]`, snapped to the sub-chunk grid.

    Snapping is required because the binary's `first_subchunk_offset` is an
    integer sub-chunk index; misalignment would drift fit windows by up to
    half a sub_s. Up to one sub_s per interval boundary is lost. The
    `chunk_days % subchunk_days == 0` invariant is enforced in
    `Zone.__post_init__` (`probes/zones.py`).
    """
    chunk_s = chunk_days * S_PER_DAY
    sub_s = subchunk_days * S_PER_DAY
    subs_per_chunk = round(chunk_days / subchunk_days)
    start_et_anchor = jd_to_et(start_jd_anchor)
    first_idx = int(math.floor((t_start_et - start_et_anchor) / chunk_s))
    last_idx = int(math.ceil((t_end_et - start_et_anchor) / chunk_s))
    out: list[tuple[int, float, float]] = []
    for idx in range(first_idx, last_idx):
        cs = start_et_anchor + idx * chunk_s
        s_offset = max(0, int(math.ceil((t_start_et - cs) / sub_s)))
        e_offset = min(subs_per_chunk, int(math.floor((t_end_et - cs) / sub_s)))
        if s_offset >= e_offset:
            continue
        s = cs + s_offset * sub_s
        e = cs + e_offset * sub_s
        out.append((idx, s, e))
    return out
