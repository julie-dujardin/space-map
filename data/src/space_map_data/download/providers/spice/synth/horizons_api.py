"""Horizons VECTORS HTTP layer: fetch, parse, window detection."""

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

from space_map_data.utils.time import jd_to_et

logger = logging.getLogger(__name__)

HORIZONS_URL = "https://ssd.jpl.nasa.gov/api/horizons.api"

# Wide-span probe to detect actual coverage window. Horizons returns whatever
# overlap exists with the requested span; we trim from the returned first/last
# sample timestamps.
WINDOW_PROBE_START = "1957-10-04"  # Sputnik 1 launch — earliest plausible
WINDOW_PROBE_END = "2100-01-01"

_J2000_DATE = datetime(2000, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@dataclass
class Sample:
    et: float
    state: tuple[float, float, float, float, float, float]


@dataclass
class HorizonsObj:
    name: str
    revised: str  # raw "Mon DD, YYYY" string as printed by Horizons
    raw: str


def _jd_to_iso(jd: float) -> str:
    """Convert JD-TDB → ISO calendar date (UTC, ±69s precision)."""
    dt = _J2000_DATE + timedelta(seconds=jd_to_et(jd))
    return dt.date().isoformat()


def _et_to_iso_dt(et: float) -> str:
    """ET seconds → `YYYY-MM-DD HH:MM:SS` (UTC, ±69s), as Horizons wants it."""
    dt = (_J2000_DATE + timedelta(seconds=et)).replace(tzinfo=None)
    return dt.isoformat(sep=" ", timespec="seconds")


def _parse_horizons_csv(text: str) -> list[Sample]:
    m = re.search(r"\$\$SOE\s*\n(.*?)\n\$\$EOE", text, re.S)
    if not m:
        return []
    rows: list[Sample] = []
    for line in m.group(1).strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 8:
            continue
        try:
            jdtdb = float(parts[0])
            x = float(parts[2])
            y = float(parts[3])
            z = float(parts[4])
            vx = float(parts[5])
            vy = float(parts[6])
            vz = float(parts[7])
        except ValueError:
            continue
        et = jd_to_et(jdtdb)
        rows.append(Sample(et, (x, y, z, vx, vy, vz)))
    return rows


def fetch_obj_data(client: httpx.Client, naif_id: int) -> HorizonsObj:
    """Probe Horizons for the spacecraft name + `Revised :` date."""
    resp = client.get(
        HORIZONS_URL,
        params={
            "format": "json",
            "COMMAND": f"'{naif_id}'",
            "OBJ_DATA": "YES",
            "MAKE_EPHEM": "NO",
        },
        timeout=60.0,
    )
    resp.raise_for_status()
    text = resp.json().get("result", "")
    rev_m = re.search(r"^\s*Revised\s*:\s*([A-Za-z]{3}\s+\d{1,2},\s*\d{4})", text, re.M)
    name_m = re.search(
        r"^\s*Revised\s*:\s*[A-Za-z]{3}\s+\d{1,2},\s*\d{4}\s+(.+?)\s+-?\d+\s*$",
        text,
        re.M,
    )
    return HorizonsObj(
        name=name_m.group(1).strip() if name_m else f"NAIF {naif_id}",
        revised=rev_m.group(1) if rev_m else "unknown",
        raw=text,
    )


def fetch_vectors(
    client: httpx.Client,
    naif_id: int,
    start: str,
    stop: str,
    step: str,
    *,
    timeout: float = 180.0,
) -> str:
    """Raw CSV text from Horizons VECTORS for `[start, stop]` at `step`."""
    resp = client.get(
        HORIZONS_URL,
        params={
            "format": "text",
            "COMMAND": f"'{naif_id}'",
            "OBJ_DATA": "NO",
            "MAKE_EPHEM": "YES",
            "EPHEM_TYPE": "VECTORS",
            "CENTER": "'@0'",
            "START_TIME": f"'{start}'",
            "STOP_TIME": f"'{stop}'",
            "STEP_SIZE": f"'{step}'",
            "REF_PLANE": "FRAME",
            "REF_SYSTEM": "J2000",
            "OUT_UNITS": "KM-S",
            "VEC_TABLE": "2",
            "CSV_FORMAT": "YES",
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.text


def _chunk_days_for_step(step: str) -> int:
    """Pick a chunk size so each request stays comfortably under Horizons'
    per-response sample cap (~90k rows). Coarser cadences span more days;
    1-minute cadence has to chunk down to ~50-day windows."""
    n, unit = step.split()
    n = int(n)
    minutes_per_sample = {"m": n, "h": n * 60, "d": n * 60 * 24}[unit]
    samples_per_day = max(1, (24 * 60) // minutes_per_sample)
    return max(1, 80_000 // samples_per_day)


def _fetch_vectors_chunked(
    client: httpx.Client,
    naif_id: int,
    start_iso: str,
    stop_iso: str,
    step: str,
    chunk_days: int | None = None,
) -> str:
    """Fetch a long span in ≤chunk_days slices; concatenate the CSVs.

    Sub-day times on `start_iso`/`stop_iso` are preserved so edge chunks keep
    the partial launch/landing days instead of snapping to midnight.

    The concatenated text has multiple $$SOE/$$EOE blocks; parse it with
    `_parse_chunks`, not `_parse_horizons_csv` (which reads only the first).
    """
    if chunk_days is None:
        chunk_days = _chunk_days_for_step(step)
    start = datetime.fromisoformat(start_iso)
    stop = datetime.fromisoformat(stop_iso)
    pieces: list[str] = []
    cur = start
    while cur < stop:
        nxt = min(stop, cur + timedelta(days=chunk_days))
        pieces.append(
            fetch_vectors(
                client,
                naif_id,
                cur.isoformat(sep=" ", timespec="seconds"),
                nxt.isoformat(sep=" ", timespec="seconds"),
                step,
            )
        )
        cur = nxt
    return "\n".join(pieces)


def _parse_chunks(text: str) -> list[Sample]:
    """Concatenated multi-chunk CSV → flat sample list (dedup adjacent epochs)."""
    out: list[Sample] = []
    last_et: float | None = None
    for block in re.findall(r"\$\$SOE\s*\n(.*?)\n\$\$EOE", text, re.S):
        for s in _parse_horizons_csv(f"$$SOE\n{block}\n$$EOE"):
            if last_et is not None and s.et == last_et:
                continue
            out.append(s)
            last_et = s.et
    return out


_NO_EPHEM_PRIOR_RE = re.compile(
    r'No ephemeris for target "[^"]+" prior to A\.D\. '
    r"(\d{4}-[A-Z]{3}-\d{2})\s+(\d{2}:\d{2}:\d{2})",
)
_NO_EPHEM_AFTER_RE = re.compile(
    r'No ephemeris for target "[^"]+" after A\.D\. '
    r"(\d{4}-[A-Z]{3}-\d{2})\s+(\d{2}:\d{2}:\d{2})",
)
_MONTHS = {
    "JAN": "01",
    "FEB": "02",
    "MAR": "03",
    "APR": "04",
    "MAY": "05",
    "JUN": "06",
    "JUL": "07",
    "AUG": "08",
    "SEP": "09",
    "OCT": "10",
    "NOV": "11",
    "DEC": "12",
}


def _horizons_date_to_iso(s: str) -> str:
    y, m, d = s.split("-")
    return f"{y}-{_MONTHS[m]}-{d}"


# Inward margin on the reported coverage edges; > the ~69s TDB↔UTC gap so the
# window stays inside coverage however Horizons reads the timescale.
_WINDOW_MARGIN = timedelta(minutes=5)


def _boundary_to_dt(date_grp: str, time_grp: str) -> datetime:
    """`('2026-APR-10', '23:54:22')` → naive `datetime`."""
    return datetime.fromisoformat(f"{_horizons_date_to_iso(date_grp)}T{time_grp}")


def detect_window(client: httpx.Client, naif_id: int) -> tuple[str, str]:
    """Find Horizons coverage by probing wide and parsing "prior to / after"
    error messages, with an adaptive step that fits short-coverage spacecraft
    yet keeps the response small over the 140-year wide span.

    Returns `(start, end)` `YYYY-MM-DD HH:MM:SS` strings pinned to the coverage edges.
    """
    start = WINDOW_PROBE_START
    end = WINDOW_PROBE_END
    lo: str | None = None  # coverage edges, pinned from boundary errors
    hi: str | None = None
    for _ in range(5):
        span_days = (
            datetime.fromisoformat(end).date() - datetime.fromisoformat(start).date()
        ).days
        step_days = max(1, span_days // 20)
        step = f"{step_days} d"
        text = fetch_vectors(client, naif_id, start, end, step)
        m_prior = _NO_EPHEM_PRIOR_RE.search(text)
        m_after = _NO_EPHEM_AFTER_RE.search(text)
        progressed = False
        if m_prior:
            dt = _boundary_to_dt(*m_prior.groups()) + _WINDOW_MARGIN
            lo = dt.isoformat(sep=" ", timespec="seconds")
            start = lo
            logger.info("naif %d: coverage START → %s (prior-to error)", naif_id, lo)
            progressed = True
        if m_after:
            dt = _boundary_to_dt(*m_after.groups()) - _WINDOW_MARGIN
            hi = dt.isoformat(sep=" ", timespec="seconds")
            end = hi
            logger.info("naif %d: coverage STOP → %s (after error)", naif_id, hi)
            progressed = True
        if progressed:
            continue
        # No errors: [start, end] is inside coverage. Any edge not pinned from
        # an error lies beyond the probe span; fall back to its extreme sample.
        samples = _parse_horizons_csv(text)
        if not samples:
            snippet = text[-400:].strip()
            raise RuntimeError(
                f"naif {naif_id}: window-probe returned no samples and no "
                f"parseable boundary message: ...{snippet!r}"
            )
        return (
            lo or _et_to_iso_dt(samples[0].et),
            hi or _et_to_iso_dt(samples[-1].et),
        )
    raise RuntimeError(f"naif {naif_id}: window-detect did not converge after 5 rounds")
