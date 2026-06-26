"""Parse the Space-Track historical TLE archive into weekly elements.

The archive (one zip per year under ``sources/position/spacetrack/archive``,
2004 split into 8 parts) holds every TLE ever issued. We distil it into one
snapshot per ISO week: for each (week, satellite) we keep the TLE whose epoch
sits nearest the week's midpoint. Output mirrors :mod:`celestrak_source` so the
Earth-zone overlay/writer consume both identically — values copy the raw TLE
fields verbatim, matching CelesTrak's GP/OMM CSV (which the frontend's
``json2satrec`` expects unconverted).
"""

import json
import logging
import zipfile
from collections.abc import Iterable, Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

from space_map_data.export.position.elements.celestrak_source import CelesTrakElements
from space_map_data.ingest.convert import mean_motion_to_a_km
from space_map_data.utils.paths import DERIVED_POSITION_DIR, SOURCES_POSITION_DIR

logger = logging.getLogger(__name__)

ARCHIVE_DIR = SOURCES_POSITION_DIR / "spacetrack" / "archive"

# Years distilled into weekly Earth snapshots — the full Space-Track archive.
ARCHIVE_YEARS: tuple[int, ...] = tuple(range(2004, 2026))

# Per-year cache of "which NORADs appear in the archive", keyed on each year's
# zip fingerprint. Lets Earth-sat ingest set has_position from archive coverage
# without re-streaming the ~12 GB archive every run.
ARCHIVE_NORAD_CACHE = DERIVED_POSITION_DIR / "spacetrack" / "archive_norads.json"

# Standard TLE pivot: 2-digit years 00-56 are 21st century, 57-99 are 20th.
_TLE_YEAR_PIVOT = 57

# JD of the Unix epoch; matches `utils.convert.date_to_julian`'s UTC convention.
_JD_UNIX_EPOCH = 2440587.5


def _decode_exp(field: str) -> float | None:
    """Decode a TLE assumed-decimal exponential field (BSTAR, n-ddot).

    ``±MMMMM±E`` → ``±0.MMMMM × 10^±E``. ``" 13035-3"`` → 1.3035e-4;
    ``" 00000-0"`` → 0.0. Returns None for a blank field.
    """
    s = field.strip()
    if not s:
        return None
    sign = 1.0
    if s[0] in "+-":
        if s[0] == "-":
            sign = -1.0
        s = s[1:]
    mantissa, exp = s[:-2], s[-2:]
    if not mantissa or not exp:
        return None
    return sign * float("0." + mantissa) * (10.0 ** int(exp))


def _parse_epoch_jd(field: str) -> float | None:
    """``YYDDD.DDDDDDDD`` → UTC Julian Date, matching ``date_to_julian``."""
    s = field.strip()
    if len(s) < 5:
        return None
    yy = int(s[:2])
    year = (2000 if yy < _TLE_YEAR_PIVOT else 1900) + yy
    doy = float(s[2:])  # 1-based day-of-year with fraction
    dt = datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=doy - 1.0)
    return dt.timestamp() / 86400.0 + _JD_UNIX_EPOCH


def parse_tle_pair(
    line1: str, line2: str
) -> tuple[int, float, CelesTrakElements] | None:
    """Parse a TLE line pair into ``(norad, epoch_jd, elements)``.

    Fixed-column slicing per the TLE spec — robust to the archive's trailing
    ``\\`` continuation and explicit ``+`` signs since both fall outside the
    read columns. ``epoch_jd`` is returned separately for week selection.
    Propagation-critical fields parse from well-separated columns; the integer
    metadata (element set, rev) is best-effort and never feeds SGP4. Returns
    None when either line is malformed.
    """
    if len(line1) < 63 or len(line2) < 63 or line1[0] != "1" or line2[0] != "2":
        return None
    try:
        norad = int(line1[2:7])
        epoch_jd = _parse_epoch_jd(line1[18:32])
        if epoch_jd is None:
            return None
        mean_motion_dot = float(line1[33:43].replace(" ", "") or "0")
        mean_motion_ddot = _decode_exp(line1[44:52])
        bstar = _decode_exp(line1[53:61])
        element_set_no = int(line1[64:68].strip() or "0")
        inclination = float(line2[8:16])
        ra_of_asc_node = float(line2[17:25])
        eccentricity = float("0." + line2[26:33].strip())
        arg_of_pericenter = float(line2[34:42])
        mean_anomaly = float(line2[43:51])
        mean_motion = float(line2[52:63])
        rev_at_epoch = int(line2[63:68].strip() or "0")
    except ValueError:
        return None
    return (
        norad,
        epoch_jd,
        CelesTrakElements(
            epoch_jd=epoch_jd,
            a=mean_motion_to_a_km(mean_motion) if mean_motion else None,
            e=eccentricity,
            i=inclination,
            om=ra_of_asc_node,
            w=arg_of_pericenter,
            ma=mean_anomaly,
            n=mean_motion,
            BSTAR=bstar,
            MEAN_MOTION_DOT=mean_motion_dot,
            MEAN_MOTION_DDOT=mean_motion_ddot,
            ELEMENT_SET_NO=element_set_no,
            REV_AT_EPOCH=rev_at_epoch,
        ),
    )


def _jd_to_datetime(jd: float) -> datetime:
    return datetime.fromtimestamp((jd - _JD_UNIX_EPOCH) * 86400.0, tz=timezone.utc)


def _week_of(epoch_jd: float) -> tuple[str, float]:
    """Return the (Monday ``YYYY-MM-DD``, week-midpoint JD) for an epoch.

    The Monday label is the snapshot's date directory; the midpoint (Monday
    00:00 UTC + 3.5d) is the reference instant we select the nearest TLE to,
    minimising the worst-case SGP4 propagation distance within the week.
    """
    dt = _jd_to_datetime(epoch_jd)
    monday = dt.date() - timedelta(days=dt.weekday())
    monday_midnight = datetime(
        monday.year, monday.month, monday.day, tzinfo=timezone.utc
    )
    monday_jd = monday_midnight.timestamp() / 86400.0 + _JD_UNIX_EPOCH
    return monday.isoformat(), monday_jd + 3.5


def year_zips(year: int) -> list[Path]:
    """Archive zip(s) for a calendar year (2004 ships as 8 parts)."""
    if year == 2004:
        parts = sorted(ARCHIVE_DIR.glob("tle2004_*of*.txt.zip"))
        return parts
    single = ARCHIVE_DIR / f"tle{year}.txt.zip"
    return [single] if single.exists() else []


def _zip_fingerprint(zip_path: Path) -> dict:
    """One archive zip as ``{name, mtime_ns, size}`` for sidecar/zone signatures."""
    st = zip_path.stat()
    return {"name": zip_path.name, "mtime_ns": st.st_mtime_ns, "size": st.st_size}


def archive_zip_fingerprints(years: Iterable[int]) -> list[dict]:
    """Fingerprint every archive zip feeding ``years`` (sorted by name).

    Folded into the Earth zone signature so adding/refreshing an archive year
    invalidates the zone's coarse skip gate.
    """
    out = [_zip_fingerprint(z) for year in years for z in year_zips(year)]
    out.sort(key=lambda e: e["name"])
    return out


def week_zip_fingerprints(date_iso: str) -> list[dict]:
    """Fingerprint the archive zip(s) that can feed the week labelled ``date_iso``.

    A Monday-anchored week spans into the next ISO year at boundaries, so both
    the Monday's and Sunday's calendar-year zips are included — a change to
    either invalidates the week's part sidecar.
    """
    monday = datetime.fromisoformat(date_iso).date()
    sunday = monday + timedelta(days=6)
    years = sorted({monday.year, sunday.year})
    out = [_zip_fingerprint(z) for y in years for z in year_zips(y)]
    out.sort(key=lambda e: e["name"])
    return out


def _iter_zip_tles(zip_path: Path) -> Iterator[tuple[int, float, CelesTrakElements]]:
    """Stream parsed TLE pairs from one archive zip (member not extracted)."""
    parsed = skipped = 0
    with zipfile.ZipFile(zip_path) as zf:
        member = zf.namelist()[0]
        with zf.open(member) as raw:
            prev: str | None = None
            for bline in raw:
                line = bline.decode("ascii", "replace").rstrip("\r\n")
                if line.startswith("1 "):
                    prev = line
                elif line.startswith("2 ") and prev is not None:
                    pair = parse_tle_pair(prev, line)
                    prev = None
                    if pair is None:
                        skipped += 1
                    else:
                        parsed += 1
                        yield pair
                else:
                    prev = None
    logger.info(
        "Parsed %d TLE pairs from %s (%d malformed pairs skipped)",
        parsed,
        zip_path.name,
        skipped,
    )


def load_archive_weeks(
    years: Iterable[int],
) -> dict[str, dict[int, CelesTrakElements]]:
    """Distil the given archive years into ``{Monday ISO date: {NORAD: elements}}``.

    Buckets every TLE by its epoch's ISO week and keeps, per satellite, the one
    whose epoch is nearest the week midpoint. Outer keys sort oldest-first.
    Bucketing is by epoch (not the zip's filename year), so a zip's year-boundary
    spillover lands in the correct week.
    """
    years = list(years)
    years_set = set(years)
    # Monday → NORAD → (distance-to-midpoint, elements).
    best: dict[str, dict[int, tuple[float, CelesTrakElements]]] = {}
    for year in years:
        zips = year_zips(year)
        if not zips:
            logger.warning("No archive zip for year %d under %s", year, ARCHIVE_DIR)
            continue
        for zip_path in zips:
            for norad, epoch_jd, elements in _iter_zip_tles(zip_path):
                monday, midpoint_jd = _week_of(epoch_jd)
                # Drop weeks anchored outside the requested years — a zip's
                # year-boundary spillover would otherwise emit sparse partial
                # weeks. They fill in once the adjacent year is included.
                if int(monday[:4]) not in years_set:
                    continue
                dist = abs(epoch_jd - midpoint_jd)
                week = best.setdefault(monday, {})
                current = week.get(norad)
                if current is None or dist < current[0]:
                    week[norad] = (dist, elements)
    result = {
        monday: {norad: ev[1] for norad, ev in week.items()}
        for monday, week in sorted(best.items())
    }
    logger.info(
        "Archive: %d weekly snapshots, %d total satellite-weeks",
        len(result),
        sum(len(w) for w in result.values()),
    )
    return result


def _scan_year_norads(year: int) -> set[int]:
    """Every catalog number appearing on a TLE line-1 in a year's archive zip(s).

    Line-1-only: we don't pair or parse the elements, just read the 5-digit
    catalog number. Across a full year every satellite has thousands of TLEs,
    so a stray malformed line can't drop it from the set — and skipping the
    full parse makes this ~10x cheaper than :func:`load_archive_weeks`. Alpha-5
    catalog numbers (>99999) fail the int parse and are skipped; those sats are
    recent enough to be in the current catalogue, so ingest already flags them.
    """
    norads: set[int] = set()
    for zip_path in year_zips(year):
        seen = 0
        with zipfile.ZipFile(zip_path) as zf:
            member = zf.namelist()[0]
            with zf.open(member) as raw:
                for bline in raw:
                    if bline[:2] != b"1 ":
                        continue
                    try:
                        norads.add(int(bline[2:7]))
                    except ValueError:
                        continue  # alpha-5 / malformed catalog number
                    seen += 1
        logger.info("Scanned %s: %d TLE line-1 records", zip_path.name, seen)
    return norads


def _load_norad_cache() -> dict:
    if not ARCHIVE_NORAD_CACHE.exists():
        return {}
    try:
        return json.loads(ARCHIVE_NORAD_CACHE.read_text())
    except (OSError, json.JSONDecodeError):
        logger.warning(
            "Unreadable archive NORAD cache %s — rebuilding", ARCHIVE_NORAD_CACHE
        )
        return {}


def _write_norad_cache(cache: dict) -> None:
    ARCHIVE_NORAD_CACHE.parent.mkdir(parents=True, exist_ok=True)
    ARCHIVE_NORAD_CACHE.write_text(json.dumps(cache))


def archive_norad_set(years: Iterable[int]) -> set[int]:
    """Union of every NORAD present in the archive across ``years``.

    Per-year results cache to :data:`ARCHIVE_NORAD_CACHE`, keyed on the year's
    zip fingerprint(s); a year re-scans only when its zip changes. The first
    build streams the whole ~12 GB archive once (minutes); steady state reads
    the small JSON cache. Used by Earth-sat ingest to set ``has_position`` on
    decayed sats that ship only in historical weeks, not the current catalogue.
    """
    years = list(years)
    cache = _load_norad_cache()
    result: set[int] = set()
    scanned = 0
    for year in years:
        if not year_zips(year):
            logger.warning("No archive zip for year %d under %s", year, ARCHIVE_DIR)
            continue
        fingerprint = archive_zip_fingerprints([year])
        entry = cache.get(str(year))
        if entry is not None and entry.get("fingerprint") == fingerprint:
            result.update(entry["norads"])
            continue
        logger.info("Archive NORAD cache miss for %d — scanning zip(s)", year)
        year_norads = _scan_year_norads(year)
        cache[str(year)] = {"fingerprint": fingerprint, "norads": sorted(year_norads)}
        result.update(year_norads)
        scanned += 1
    if scanned:
        _write_norad_cache(cache)
    logger.info(
        "Archive NORAD set: %d distinct satellites (%d year(s) rescanned)",
        len(result),
        scanned,
    )
    return result
