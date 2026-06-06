"""Load CelesTrak GP/TLE elements from disk for export overlay.

The DB is authoritative for satellite metadata (SATCAT, names, constellation
tags), but orbital elements are time-stamped and we keep one snapshot per day
on disk. The exporter reads every day-dir so the frontend can pick a snapshot
near the user's simulated time, instead of always propagating from the latest.
"""

import csv
import logging
from pathlib import Path
from typing import TypedDict

from space_map_data.ingest.convert import (
    float_or_none,
    int_or_none,
    mean_motion_to_a_km,
)
from space_map_data.utils.convert import date_to_julian

logger = logging.getLogger(__name__)


class CelesTrakElements(TypedDict):
    """One day's GP/TLE row for a single satellite, in the shape consumed by
    the export overlay. Keys mirror the Object/CelesTrak attributes they
    overwrite."""

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
    logger.info(
        "Loaded %d CelesTrak elements from %s (%d from group CSVs only)",
        len(out),
        day_dir,
        group_only,
    )
    return out


def load_all_days(download_dir: Path) -> dict[str, dict[int, CelesTrakElements]]:
    """Return every available day's GP elements indexed by ISO date → NORAD.

    Outer keys are ``YYYY-MM-DD`` strings sorted oldest-first; inner values
    match :func:`_parse_row` output. Empty result if no day-dirs are present.
    """
    celestrak_dir = download_dir / "sources" / "position" / "celestrak"
    days = iter_day_dirs(celestrak_dir)
    if not days:
        logger.warning(
            "No CelesTrak day-dirs under %s; Earth zone export will be empty",
            celestrak_dir,
        )
        return {}
    return {iso: _load_day(day_dir) for iso, day_dir in days}
