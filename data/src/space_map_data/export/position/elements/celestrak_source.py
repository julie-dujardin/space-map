"""Load GP/TLE elements from disk for export overlay.

The DB is authoritative for satellite metadata (SATCAT, names, constellation
tags), but orbital elements are time-stamped and we keep one snapshot per day
on disk. The exporter reads every day-dir so the frontend can pick a snapshot
near the user's simulated time, instead of always propagating from the latest.

Elements come from Space-Track alone. CelesTrak's GROUP=active fed this path
until the weekly backfill closed the 2026 gap; it is a ~18k subset of
Space-Track's ~32k catalogue, so mixing the two made a day's object count depend
on which provider happened to supply it. CelesTrak is still downloaded for
classification (SATCAT, constellation and category groups) — just not for
ephemeris.
"""

import bisect
import csv
import logging
from pathlib import Path
from typing import TypedDict

from tqdm import tqdm

from space_map_data.ingest.convert import (
    float_or_none,
    int_or_none,
    mean_motion_to_a_km,
)
from space_map_data.utils.convert import date_to_julian

logger = logging.getLogger(__name__)

# How far back a Space-Track snapshot may reach for a satellite it has no
# elements for. A weekly pull covers every object tracked that week, but 2-5% of
# the catalogue gets no TLE at all in a given week (much more when tracking
# stalls), and those objects would otherwise vanish from the scene for that week.
#
# Strictly backwards: a later element set can encode a manoeuvre that had not
# happened yet at this date, which would draw a satellite on a trajectory it has
# not flown.
#
# Measured on the 2025 archive, looking back 30 days lifts weekly coverage from
# ~95% to ~96.6%, and — unlike a shorter reach — holds up on weeks with a
# tracking gap, where 7 days still leaves ~11% missing. Costs no extra downloads:
# the earlier snapshots are already on disk.
FILL_LOOKBACK_DAYS = 30.0


class CelesTrakElements(TypedDict):
    """One day's GP/TLE row for a satellite, keyed to match the Object/CelesTrak
    attributes they overwrite."""

    epoch_jd: float | None
    a: float | None
    e: float | None
    i: float | None
    om: float | None
    w: float | None
    ma: float | None
    n: float | None
    BSTAR: float | None
    MEAN_MOTION_DOT: float | None
    MEAN_MOTION_DDOT: float | None
    ELEMENT_SET_NO: int | None
    REV_AT_EPOCH: int | None


def iter_day_dirs(celestrak_dir: Path) -> list[tuple[str, Path]]:
    """Return every ``<year>/<month>/<day>/`` directory, oldest first.

    The ISO date (``YYYY-MM-DD``) is paired with the path so callers don't
    have to re-derive it.
    """
    if not celestrak_dir.exists():
        return []
    out: list[tuple[str, Path]] = []
    for year_dir in celestrak_dir.iterdir():
        if not (year_dir.is_dir() and year_dir.name.isdigit()):
            continue
        for month_dir in year_dir.iterdir():
            if not (month_dir.is_dir() and month_dir.name.isdigit()):
                continue
            for day_dir in month_dir.iterdir():
                if not (day_dir.is_dir() and day_dir.name.isdigit()):
                    continue
                iso = f"{int(year_dir.name):04d}-{int(month_dir.name):02d}-{int(day_dir.name):02d}"
                out.append((iso, day_dir))
    out.sort(key=lambda t: t[0])
    return out


def current_day_dirs(download_dir: Path) -> list[tuple[str, Path]]:
    """Daily element snapshots from ``spacetrack/current``, oldest first."""
    position_dir = download_dir / "sources" / "position"
    return iter_day_dirs(position_dir / "spacetrack" / "current")


def _parse_row(row: dict) -> tuple[int, CelesTrakElements] | None:
    """Extract orbital elements + SGP4 fields from a GP CSV row."""
    norad = int_or_none(row.get("NORAD_CAT_ID"))
    if norad is None:
        return None
    mean_motion = float_or_none(row["MEAN_MOTION"])
    a_km = mean_motion_to_a_km(mean_motion) if mean_motion else None
    return norad, CelesTrakElements(
        epoch_jd=date_to_julian(row["EPOCH"]),
        a=a_km,
        e=float_or_none(row["ECCENTRICITY"]),
        i=float_or_none(row["INCLINATION"]),
        om=float_or_none(row["RA_OF_ASC_NODE"]),
        w=float_or_none(row["ARG_OF_PERICENTER"]),
        ma=float_or_none(row["MEAN_ANOMALY"]),
        n=mean_motion,
        BSTAR=float_or_none(row["BSTAR"]),
        MEAN_MOTION_DOT=float_or_none(row["MEAN_MOTION_DOT"]),
        MEAN_MOTION_DDOT=float_or_none(row["MEAN_MOTION_DDOT"]),
        ELEMENT_SET_NO=int_or_none(row["ELEMENT_SET_NO"]),
        REV_AT_EPOCH=int_or_none(row["REV_AT_EPOCH"]),
    )


def _load_day(day_dir: Path) -> dict[int, CelesTrakElements]:
    """Read ``gp-active.csv`` + ``groups/*.csv`` from one day-dir."""
    out: dict[int, CelesTrakElements] = {}
    gp_active = day_dir / "gp-active.csv"
    if gp_active.exists():
        with open(gp_active, newline="") as f:
            for row in csv.DictReader(f):
                parsed = _parse_row(row)
                if parsed is not None:
                    out[parsed[0]] = parsed[1]
    else:
        logger.warning("gp-active.csv missing in %s", day_dir)

    group_only = 0
    groups_dir = day_dir / "groups"
    if groups_dir.exists():
        for group_file in sorted(groups_dir.glob("*.csv")):
            if group_file.stat().st_size == 0:
                continue
            with open(group_file, newline="") as f:
                for row in csv.DictReader(f):
                    parsed = _parse_row(row)
                    if parsed is None:
                        continue
                    norad, elements = parsed
                    if norad not in out:
                        out[norad] = elements
                        group_only += 1
    logger.debug(
        "Loaded %d CelesTrak elements from %s (%d from group CSVs only)",
        len(out),
        day_dir,
        group_only,
    )
    return out


def fill_gaps(
    days: dict[str, dict[int, CelesTrakElements]],
    donors: dict[str, dict[int, CelesTrakElements]] | None = None,
) -> None:
    """Fill each snapshot's missing satellites from earlier ones.

    ``donors`` supplies extra earlier snapshots that are read but never filled —
    the tail of the archive year, so the first weeks of the current year can
    look back across the year boundary instead of starting from nothing.

    A satellite absent from a snapshot takes the most recent element set from
    at or before that snapshot's date, within :data:`FILL_LOOKBACK_DAYS`.
    Entries are shared by reference, not copied — the frontend reads each row's
    own ``epoch_jd``, so a filled row carries its true age and renders with the
    stale-element warning rather than pretending to be current.
    """
    if not days:
        return
    # NORAD -> its element sets across every snapshot, epochs kept in a parallel
    # sorted list so each lookup is a bisect rather than a scan over snapshots.
    seen: dict[int, list[tuple[float, CelesTrakElements]]] = {}
    for elements in [*(donors or {}).values(), *days.values()]:
        for norad, row in elements.items():
            epoch = row["epoch_jd"]
            if epoch is not None:
                seen.setdefault(norad, []).append((epoch, row))
    epochs_by_norad: dict[int, list[float]] = {}
    rows_by_norad: dict[int, list[CelesTrakElements]] = {}
    for norad, entries in seen.items():
        entries.sort(key=lambda t: t[0])
        epochs_by_norad[norad] = [epoch for epoch, _row in entries]
        rows_by_norad[norad] = [row for _epoch, row in entries]

    filled = 0
    for iso, elements in days.items():
        target_jd = date_to_julian(iso)
        if target_jd is None:
            continue
        for norad, epochs in epochs_by_norad.items():
            if norad in elements:
                continue
            # Rightmost epoch at or before the target — never a later one.
            idx = bisect.bisect_right(epochs, target_jd) - 1
            if idx >= 0 and target_jd - epochs[idx] <= FILL_LOOKBACK_DAYS:
                elements[norad] = rows_by_norad[norad][idx]
                filled += 1
    logger.info(
        "Filled %d satellite-days from earlier snapshots (%gd lookback)",
        filled,
        FILL_LOOKBACK_DAYS,
    )


def load_all_days(
    download_dir: Path,
    donors: dict[str, dict[int, CelesTrakElements]] | None = None,
) -> dict[str, dict[int, CelesTrakElements]]:
    """Return every available day's GP elements indexed by ISO date → NORAD.

    Outer keys are ``YYYY-MM-DD`` strings sorted oldest-first; inner values
    match :func:`_parse_row` output. Empty result if no day-dirs are present.
    Gaps are filled from earlier snapshots, and from ``donors`` — the archive
    year's tail, which the caller supplies so this module stays independent of
    the archive reader. See :func:`fill_gaps`.
    """
    days = current_day_dirs(download_dir)
    if not days:
        logger.warning(
            "No Space-Track day-dirs under %s; Earth zone export will be empty",
            download_dir / "sources" / "position" / "spacetrack" / "current",
        )
        return {}
    result = {
        iso: _load_day(day_dir)
        for iso, day_dir in tqdm(days, desc="CelesTrak days", unit="day")
    }
    total = sum(len(d) for d in result.values())
    logger.info("Loaded %d CelesTrak elements across %d days", total, len(result))
    fill_gaps(result, donors)
    return result
