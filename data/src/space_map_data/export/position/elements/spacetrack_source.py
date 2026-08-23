"""Parse the Space-Track historical TLE archive into weekly elements.

The archive (one zip per year under ``sources/position/spacetrack/archive``,
2004 split into 8 parts) holds every TLE ever issued. Distilled into one
snapshot per ISO week: for each (week, satellite), the TLE whose epoch sits
nearest the week's midpoint. Output mirrors :mod:`celestrak_source` so the
Earth-zone overlay/writer consume both identically.
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

# Years distilled into weekly Earth snapshots — back to the dawn of the
# catalogue, since the 2004 zip is a full historical dump (see _source_zips_for).
ARCHIVE_YEARS: tuple[int, ...] = tuple(range(1959, 2026))

# Per-year cache of "which NORADs ship in the archive weeks", keyed on each
# year's zip fingerprint. Lets Earth-sat ingest set has_position without
# re-streaming the ~12 GB archive every run.
ARCHIVE_NORAD_CACHE = DERIVED_POSITION_DIR / "spacetrack" / "archive_norads.json"

# Bump on a scan-logic change: the cache keys on zip fingerprints, which don't
# move when only code changes, so a stale cache would otherwise survive.
_NORAD_SCAN_VERSION = 3

# Weekly snapshots from the end of the newest archive year, cached so the
# current-year snapshots can fill their gaps across the year boundary. Without
# it the first weeks of the backfilled year have nothing behind them to look
# back to, and objects untracked that week vanish from the scene.
ARCHIVE_TAIL_CACHE = DERIVED_POSITION_DIR / "spacetrack" / "archive_tail.json"
_TAIL_VERSION = 1

# Same problem one layer up — bump to force every archive year to re-distil
# when which TLEs land in which week changes.
ARCHIVE_WEEK_VERSION = 2

# The 2004 archive is a full historical dump; no per-year zips exist before
# it, so every year up to 2004 reads its 8 parts. Later tleYYYY zips are
# yearly increments feeding only their own year.
_MEGA_DUMP_YEAR = 2004

# Standard TLE pivot: 2-digit years 00-56 are 21st century, 57-99 are 20th.
_TLE_YEAR_PIVOT = 57

# JD of the Unix epoch; matches `utils.convert.date_to_julian`'s UTC convention.
_JD_UNIX_EPOCH = 2440587.5


def _decode_exp(field: str) -> float | None:
    """Decode a TLE assumed-decimal exponential field (BSTAR, n-ddot):
    ``±MMMMM±E`` → ``±0.MMMMM × 10^±E``. Returns None for a blank field."""
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

    Fixed-column slicing per the TLE spec, robust to the archive's trailing
    ``\\`` continuation and explicit ``+`` signs (both fall outside read
    columns). Returns None when either line is malformed.
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


def _week_of(epoch_jd: float) -> tuple[str, float, int]:
    """Return the (Monday ``YYYY-MM-DD``, week-midpoint JD, owner year) for an epoch.

    The midpoint (Thursday noon) is the reference instant we pick the nearest
    TLE to, minimising worst-case SGP4 propagation distance. The owner year is
    the midpoint's calendar year — see :func:`load_archive_weeks`.
    """
    dt = _jd_to_datetime(epoch_jd)
    monday = dt.date() - timedelta(days=dt.weekday())
    monday_midnight = datetime(
        monday.year, monday.month, monday.day, tzinfo=timezone.utc
    )
    monday_jd = monday_midnight.timestamp() / 86400.0 + _JD_UNIX_EPOCH
    return monday.isoformat(), monday_jd + 3.5, (monday + timedelta(days=3)).year


def year_zips(year: int) -> list[Path]:
    """Archive zip(s) physically named for a calendar year (2004 ships as 8 parts)."""
    if year == 2004:
        parts = sorted(ARCHIVE_DIR.glob("tle2004_*of*.txt.zip"))
        return parts
    single = ARCHIVE_DIR / f"tle{year}.txt.zip"
    return [single] if single.exists() else []


def _source_zips_for(year: int) -> list[Path]:
    """Physical archive zip(s) whose epochs cover output ``year``. Pre-2004
    history lives in the 2004 mega-dump, so every year ≤ 2004 resolves there.
    """
    return year_zips(_MEGA_DUMP_YEAR if year <= _MEGA_DUMP_YEAR else year)


def archive_source_groups(years: Iterable[int]) -> list[tuple[str, list[int]]]:
    """Partition ``years`` into ``(label, years)`` groups by shared physical
    source. Years ≤ 2004 collapse into one ``"2004"`` group parsed in a single
    streaming pass instead of re-reading the ~2 GB dump per year; later years
    stand alone. The label doubles as the sidecar/cache key.
    """
    years = sorted(set(years))
    groups: list[tuple[str, list[int]]] = []
    mega = [y for y in years if y <= _MEGA_DUMP_YEAR]
    if mega:
        groups.append((str(_MEGA_DUMP_YEAR), mega))
    groups.extend((str(y), [y]) for y in years if y > _MEGA_DUMP_YEAR)
    return groups


def _claim_sets(years: Iterable[int]) -> tuple[set[int], set[int]]:
    """``(owned, tail)`` year sets implementing the week-ownership rule.

    ``owned``: a week whose midpoint falls in one of these years is built
    here. ``tail``: years with no successor zip, so their trailing December
    week is kept from their own fragment instead of lost off the archive end.
    """
    owned = set(years)
    return owned, {y for y in owned if not _source_zips_for(y + 1)}


def _zip_fingerprint(zip_path: Path) -> dict:
    """One archive zip as ``{name, mtime_ns, size}`` for sidecar/zone signatures."""
    st = zip_path.stat()
    return {"name": zip_path.name, "mtime_ns": st.st_mtime_ns, "size": st.st_size}


def _dedup_fingerprints(years: Iterable[int]) -> list[dict]:
    """Fingerprint each distinct source zip feeding ``years``, sorted by name.
    De-duped by name so pre-2004 years sharing the mega-dump don't repeat its
    8 parts once per year."""
    by_name: dict[str, dict] = {}
    for year in years:
        for z in _source_zips_for(year):
            by_name.setdefault(z.name, _zip_fingerprint(z))
    return [by_name[name] for name in sorted(by_name)]


def archive_zip_fingerprints(years: Iterable[int]) -> list[dict]:
    """Fingerprint every distinct archive zip feeding ``years``. Folded into
    the Earth zone signature so refreshing an archive year invalidates the
    zone's coarse skip gate."""
    return _dedup_fingerprints(years)


def week_zip_fingerprints(date_iso: str) -> list[dict]:
    """Fingerprint the archive zip(s) that can feed the week labelled
    ``date_iso``. Both Monday's and Sunday's year are fingerprinted, even
    though the week is built from the midpoint year's zip alone — a superset
    only over-invalidates, and stays correct if archive cut points move.
    """
    monday = datetime.fromisoformat(date_iso).date()
    sunday = monday + timedelta(days=6)
    return _dedup_fingerprints({monday.year, sunday.year})


def _archive_member(zf: zipfile.ZipFile, zip_path: Path) -> str:
    """The TLE text member of an archive zip. Upstream repacks vary the layout
    (macOS AppleDouble entries, a nested ``data/exports/`` prefix), so select
    by extension and size rather than taking the first entry, which would
    silently read junk for a whole year."""
    members = [
        info
        for info in zf.infolist()
        if not info.is_dir()
        and info.filename.endswith(".txt")
        and not info.filename.rpartition("/")[2].startswith("._")
    ]
    if not members:
        raise ValueError(f"No TLE text member in {zip_path.name}: {zf.namelist()!r}")
    return max(members, key=lambda info: info.file_size).filename


def _iter_zip_tles(zip_path: Path) -> Iterator[tuple[int, float, CelesTrakElements]]:
    """Stream parsed TLE pairs from one archive zip (member not extracted)."""
    parsed = skipped = 0
    with zipfile.ZipFile(zip_path) as zf:
        member = _archive_member(zf, zip_path)
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
    log = logger.warning if parsed == 0 else logger.info
    log(
        "Parsed %d TLE pairs from %s member %s (%d malformed pairs skipped)",
        parsed,
        zip_path.name,
        member,
        skipped,
    )


def load_archive_weeks(
    years: Iterable[int],
) -> dict[str, dict[int, CelesTrakElements]]:
    """Distil the given archive years into ``{Monday ISO date: {NORAD: elements}}``.

    Keeps, per satellite per week, the TLE nearest the week midpoint. A week
    is owned by the calendar year of its *midpoint*, not its Monday — this
    matches how each ``tleYYYY`` zip is cut (a few days before Jan 1 through
    Dec 31), so a boundary week's zip holds the whole week rather than just
    its December fragment. The newest archive year is the exception: nothing
    succeeds it, so it keeps its own trailing week.
    """
    years = list(years)
    owned, tail = _claim_sets(years)
    # Monday → NORAD → (distance-to-midpoint, elements).
    best: dict[str, dict[int, tuple[float, CelesTrakElements]]] = {}
    # Dedup by path so the shared 2004 mega-dump isn't re-read per year.
    seen: set[Path] = set()
    sources: list[Path] = []
    for year in years:
        for z in _source_zips_for(year):
            if z not in seen:
                seen.add(z)
                sources.append(z)
    if not sources:
        logger.warning("No archive zips for years %r under %s", years, ARCHIVE_DIR)
    for zip_path in sources:
        for norad, epoch_jd, elements in _iter_zip_tles(zip_path):
            monday, midpoint_jd, owner_year = _week_of(epoch_jd)
            # Drop weeks owned by another year — a zip carries a tail of the
            # neighbouring years, which would otherwise emit sparse partial
            # weeks. They fill in once their owning year is included.
            if owner_year not in owned and int(monday[:4]) not in tail:
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


def load_archive_tail(lookback_days: float) -> dict[str, dict[int, CelesTrakElements]]:
    """Weekly snapshots covering the final ``lookback_days`` of the archive.

    Donor-only material for :func:`celestrak_source.fill_gaps`, so a satellite
    missing from the first weeks of the backfilled year can still be placed from
    late in the archive year before it. Cached on the newest year's zip
    fingerprint — distilling it means streaming that year's ~3 GB of TLEs, which
    is not worth repeating per export.
    """
    newest = max(ARCHIVE_YEARS)
    fingerprint = archive_zip_fingerprints([newest])
    cached = _load_tail_cache()
    if (
        cached.get("fingerprint") == fingerprint
        and cached.get("lookback_days") == lookback_days
    ):
        return {
            monday: {int(n): e for n, e in week.items()}
            for monday, week in cached["weeks"].items()
        }

    zips = _source_zips_for(newest)
    if not zips:
        logger.warning("No archive zip for %d; year-boundary fill unavailable", newest)
        return {}
    # Last instant the archive year covers, minus the lookback.
    end_jd = (
        datetime(newest + 1, 1, 1, tzinfo=timezone.utc).timestamp() / 86400.0
        + _JD_UNIX_EPOCH
    )
    cutoff_jd = end_jd - lookback_days
    best: dict[str, dict[int, tuple[float, CelesTrakElements]]] = {}
    for zip_path in zips:
        for norad, epoch_jd, elements in _iter_zip_tles(zip_path):
            if epoch_jd < cutoff_jd:
                continue
            monday, midpoint_jd, _owner = _week_of(epoch_jd)
            dist = abs(epoch_jd - midpoint_jd)
            week = best.setdefault(monday, {})
            current = week.get(norad)
            if current is None or dist < current[0]:
                week[norad] = (dist, elements)
    result = {
        monday: {norad: ev[1] for norad, ev in week.items()}
        for monday, week in sorted(best.items())
    }
    _write_tail_cache(fingerprint, lookback_days, result)
    logger.info(
        "Archive tail: %d week(s) from %d, %d satellite-weeks",
        len(result),
        newest,
        sum(len(w) for w in result.values()),
    )
    return result


def _load_tail_cache() -> dict:
    """Load the archive-tail cache, or {} if absent/unreadable/stale."""
    if not ARCHIVE_TAIL_CACHE.exists():
        return {}
    try:
        cache = json.loads(ARCHIVE_TAIL_CACHE.read_text())
    except OSError, json.JSONDecodeError:
        logger.warning(
            "Unreadable archive tail cache %s — rebuilding", ARCHIVE_TAIL_CACHE
        )
        return {}
    if cache.get("version") != _TAIL_VERSION:
        return {}
    return cache


def _write_tail_cache(
    fingerprint: list[dict],
    lookback_days: float,
    weeks: dict[str, dict[int, CelesTrakElements]],
) -> None:
    ARCHIVE_TAIL_CACHE.parent.mkdir(parents=True, exist_ok=True)
    ARCHIVE_TAIL_CACHE.write_text(
        json.dumps(
            {
                "version": _TAIL_VERSION,
                "fingerprint": fingerprint,
                "lookback_days": lookback_days,
                "weeks": weeks,
            }
        )
    )


def _scan_source_norads(zips: list[Path], out_years: Iterable[int]) -> set[int]:
    """NORADs whose distilled week lands in ``out_years``, scanning ``zips``
    once. Buckets by epoch week (not raw epoch) to match
    :func:`load_archive_weeks` exactly, so a satellite that decayed before
    the window is correctly excluded.
    """
    owned, tail = _claim_sets(out_years)
    norads: set[int] = set()
    for zp in zips:
        for norad, epoch_jd, _elements in _iter_zip_tles(zp):
            monday, _midpoint_jd, owner_year = _week_of(epoch_jd)
            if owner_year in owned or int(monday[:4]) in tail:
                norads.add(norad)
    return norads


def _load_norad_cache() -> dict:
    """Load the per-year cache, or {} if absent/unreadable/stale. A version
    mismatch returns {} — fingerprints alone can't catch a scan-logic change.
    """
    if not ARCHIVE_NORAD_CACHE.exists():
        return {}
    try:
        cache = json.loads(ARCHIVE_NORAD_CACHE.read_text())
    except OSError, json.JSONDecodeError:
        logger.warning(
            "Unreadable archive NORAD cache %s — rebuilding", ARCHIVE_NORAD_CACHE
        )
        return {}
    if cache.get("version") != _NORAD_SCAN_VERSION:
        logger.info(
            "Archive NORAD cache version %r != %r — rebuilding",
            cache.get("version"),
            _NORAD_SCAN_VERSION,
        )
        return {}
    return cache


def _write_norad_cache(cache: dict) -> None:
    cache["version"] = _NORAD_SCAN_VERSION
    ARCHIVE_NORAD_CACHE.parent.mkdir(parents=True, exist_ok=True)
    ARCHIVE_NORAD_CACHE.write_text(json.dumps(cache))


def archive_norad_set(years: Iterable[int]) -> set[int]:
    """Union of every NORAD present in the archive across ``years``.

    Cached per source group, keyed on zip fingerprint + year span, so a group
    only re-scans when its inputs change. Used by Earth-sat ingest to set
    ``has_position`` on decayed sats that ship only in historical weeks.
    """
    cache = _load_norad_cache()
    result: set[int] = set()
    scanned = 0
    for label, group_years in archive_source_groups(years):
        zips = _source_zips_for(group_years[0])
        if not zips:
            logger.warning("No archive zip for group %s under %s", label, ARCHIVE_DIR)
            continue
        fingerprint = archive_zip_fingerprints(group_years)
        entry = cache.get(label)
        if (
            entry is not None
            and entry.get("fingerprint") == fingerprint
            and entry.get("years") == group_years
        ):
            result.update(entry["norads"])
            continue
        logger.info("Archive NORAD cache miss for group %s — scanning zip(s)", label)
        group_norads = _scan_source_norads(zips, group_years)
        cache[label] = {
            "fingerprint": fingerprint,
            "years": group_years,
            "norads": sorted(group_norads),
        }
        result.update(group_norads)
        scanned += 1
    if scanned:
        _write_norad_cache(cache)
    logger.info(
        "Archive NORAD set: %d distinct satellites (%d group(s) rescanned)",
        len(result),
        scanned,
    )
    return result
