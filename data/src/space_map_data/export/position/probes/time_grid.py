"""Time-axis math for the probes exporter.

Pure helpers — no SPICE, no zone state — used by classify/fit/write passes
to convert between JD/ET and to slice probe coverage onto the streaming
chunk grid anchored at `PROBE_EXPORT_START_YEAR`.
"""

import datetime
import math

S_PER_DAY = 86400.0
J2000_JD = 2451545.0

# Chunk grid anchor — chebyshev uses 1950-01-01, we share it. End year is
# bumped past chebyshev's 2050 because predicted-ephemeris kernels reach
# well into the late 21st century (Voyager Interstellar Mission kernels go
# to ~2120, JWST predicted to ~2050, HERA / SOLAR-ORBITER predict to 2030+).
# Setting end past every kernel keeps the manifest's `chunks` count an
# upper bound on the max chunk index the writer can emit.
PROBE_EXPORT_START_YEAR = 1950
PROBE_EXPORT_END_YEAR = 2150


def year_to_jd(year: int) -> float:
    """Civil-year start (Jan 1) → Julian Date TDB (matching chebyshev writer)."""
    d = datetime.date(year, 1, 1)
    return d.toordinal() + 1721424.5


def et_to_jd(et: float) -> float:
    return J2000_JD + et / S_PER_DAY


def jd_to_et(jd: float) -> float:
    return (jd - J2000_JD) * S_PER_DAY


def landed_chunk_range(
    chunk_years: float,
    t_start_et: float,
    t_end_et: float,
    start_jd_anchor: float,
) -> list[tuple[int, float, float]]:
    """Slice a landed phase across streaming chunks. Unlike
    `chunk_aligned_range` (used by flying contributions), this does NOT
    snap to the sub-chunk grid — the landed record carries its own start/
    end ET offsets inside the chunk and lives outside the grid timing."""
    chunk_s = chunk_years * 365.25 * S_PER_DAY
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
    chunk_years: float,
    subchunk_days: float,
    t_start_et: float,
    t_end_et: float,
    start_jd_anchor: float,
) -> list[tuple[int, float, float]]:
    """Return `[(chunk_idx, sub_t_start_et, sub_t_end_et), ...]` covering
    `[t_start_et, t_end_et]`, where the returned `(s, e)` snap to the
    SUB-CHUNK grid anchored at `chunk_start_et`.

    Snapping matters: the binary's `first_subchunk_offset` is an integer
    sub-chunk index, so sub-chunk boundaries must land on
    `chunk_start_et + k * sub_s` exactly. Without the snap the fits would
    happen on interval-aligned windows but the binary would record them on
    chunk-aligned indices, drifting up to half a sub_s — millions of km of
    phase error on cruise probes.

    Loses up to one sub_s per interval boundary (coverage trailing past
    the last grid point gets dropped), which is at most a few days even
    for interplanetary (7-day sub-chunks).
    """
    chunk_s = chunk_years * 365.25 * S_PER_DAY
    sub_s = subchunk_days * S_PER_DAY
    start_et_anchor = jd_to_et(start_jd_anchor)
    first_idx = int(math.floor((t_start_et - start_et_anchor) / chunk_s))
    last_idx = int(math.ceil((t_end_et - start_et_anchor) / chunk_s))
    subs_per_chunk = int(chunk_s / sub_s)
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
