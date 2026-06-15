"""Shared enrichment logic for CelesTrak-sourced satellites.

Used by both the SATCAT ingestor (all 65k rows) and the CelesTrak TLE
ingestor (group-only fallback rows).
"""

import csv
import logging
from pathlib import Path

import re

from space_map_data.constants.earth_sats.constellations import (
    CLASSIFIED_BY_OWNER,
    CONSTELLATION_BY_SLUG,
    GROUP_TO_CATEGORY,
    GROUP_TO_SLUG,
    PREFERRED_SLUGS,
    SOURCE_TO_SLUG,
    UNPREFERRED_SLUGS,
    slug_from_cospar,
    slug_from_name,
)
from space_map_data.constants.earth_sats.launch_sites import LAUNCH_SITE_CODES
from space_map_data.constants.earth_sats.manufacturers import (
    MANUFACTURER_BY_CONSTELLATION,
)
from space_map_data.constants.earth_sats.operators import (
    OPERATOR_BY_CONSTELLATION,
    OPERATOR_BY_SOURCE,
    operator_overlaps,
)
from space_map_data.constants.earth_sats.satcat import (
    parse_data_status,
    parse_object_type,
    parse_ops_status,
    parse_orbit_center,
    parse_orbit_type,
)
from space_map_data.constants.earth_sats.satellite_models import bus_for_satellite
from space_map_data.constants.earth_sats.sources import SOURCE_BY_CODE, parse_source
from space_map_data.ingest.convert import float_or_none, int_or_none, string_or_none

logger = logging.getLogger(__name__)

_CLASSIFIED_NAME = re.compile(r"^OBJECT [A-Z]{1,2}$")


# ---------------------------------------------------------------------------
# Group-CSV loading
# ---------------------------------------------------------------------------


class GroupData:
    """Result of loading CelesTrak group CSVs."""

    __slots__ = ("by_norad", "by_cospar", "group_only_rows")

    def __init__(self) -> None:
        self.by_norad: dict[int, set[str]] = {}
        self.by_cospar: dict[str, set[str]] = {}
        # Full GP/TLE rows for sats present only in group CSVs (not in
        # gp-active.csv).  Keyed by NORAD; first occurrence wins.
        self.group_only_rows: dict[int, dict[str, str]] = {}


def latest_day_dir(provider_dir: Path) -> Path:
    """Find the newest <year>/<month>/<day>/ snapshot under a download dir.

    Falls back to the provider dir itself when no day-tiered snapshot exists,
    so existing run_path handling (``csv_path.exists()`` skip) keeps working.
    """
    if not provider_dir.exists():
        return provider_dir
    latest: tuple[int, int, int, Path] | None = None
    for year_dir in provider_dir.iterdir():
        if not (year_dir.is_dir() and year_dir.name.isdigit()):
            continue
        for month_dir in year_dir.iterdir():
            if not (month_dir.is_dir() and month_dir.name.isdigit()):
                continue
            for day_dir in month_dir.iterdir():
                if not (day_dir.is_dir() and day_dir.name.isdigit()):
                    continue
                key = (int(year_dir.name), int(month_dir.name), int(day_dir.name))
                if latest is None or key > latest[:3]:
                    latest = (*key, day_dir)
    return latest[3] if latest is not None else provider_dir


def load_groups(groups_dir: Path) -> GroupData:
    """Parse group CSVs and return membership + TLE-fallback data."""
    data = GroupData()
    if not groups_dir.exists():
        logger.warning("Groups dir not found at %s; skipping group tagging", groups_dir)
        return data
    for group_file in sorted(groups_dir.glob("*.csv")):
        group = group_file.stem
        if group not in GROUP_TO_SLUG and group not in GROUP_TO_CATEGORY:
            logger.warning(
                "Group file %s has no mapped slug or category; skipping",
                group_file.name,
            )
            continue
        if group_file.stat().st_size == 0:
            logger.info("Group file %s is empty", group_file.name)
            continue
        count = 0
        with open(group_file, newline="") as f:
            for row in csv.DictReader(f):
                norad = int_or_none(row.get("NORAD_CAT_ID"))
                if norad is None:
                    continue
                data.by_norad.setdefault(norad, set()).add(group)
                cospar = string_or_none(row.get("OBJECT_ID"))
                if cospar is not None:
                    data.by_cospar.setdefault(cospar, set()).add(group)
                data.group_only_rows.setdefault(norad, row)
                count += 1
        logger.info("Group %s -> %d sats", group, count)
    return data


def groups_for(
    norad: int,
    cospar: str | None,
    group_data: GroupData,
) -> set[str]:
    """Collect all group slugs for a satellite from both NORAD and COSPAR."""
    groups = set(group_data.by_norad.get(norad, set()))
    if cospar is not None:
        groups |= group_data.by_cospar.get(cospar, set())
    return groups


# ---------------------------------------------------------------------------
# Enrichment resolution
# ---------------------------------------------------------------------------


def resolve_constellation(
    norad: int,
    name: str | None,
    owner: str | None,
    groups: set[str],
    cospar: str | None = None,
) -> str | None:
    """Pick a single constellation slug; log an error if candidates disagree."""
    candidates: list[tuple[str, str]] = []  # (source, slug)
    name_slug = slug_from_name(name)
    if name_slug is not None:
        candidates.append(("name-prefix", name_slug))
    cospar_slug = slug_from_cospar(cospar)
    if cospar_slug is not None:
        candidates.append(("object-id-prefix", cospar_slug))
    for group in groups:
        group_slug = GROUP_TO_SLUG.get(group)
        if group_slug is not None:
            candidates.append((f"group:{group}", group_slug))
    if owner is not None:
        owner_slug = SOURCE_TO_SLUG.get(owner)
        if owner_slug is not None:
            candidates.append((f"owner:{owner}", owner_slug))

    # Classified fallback: "OBJECT A" style names → country's classified constellation
    if not candidates and name is not None and owner is not None:
        if _CLASSIFIED_NAME.match(name):
            classified_slug = CLASSIFIED_BY_OWNER.get(owner)
            if classified_slug is not None:
                return classified_slug

    if not candidates:
        return None
    unique = {slug for _, slug in candidates}
    if len(unique) == 1:
        return candidates[0][1]

    preferred = next(
        (slug for slug in PREFERRED_SLUGS if slug in unique),
        None,
    )
    if preferred is not None:
        return preferred
    filtered = [c for c in candidates if c[1] not in UNPREFERRED_SLUGS]
    if filtered and {slug for _, slug in filtered} != unique:
        return filtered[0][1]
    logger.error(
        "NORAD %d has conflicting constellation matches: %s — picking %s",
        norad,
        ", ".join(f"{src}={slug}" for src, slug in candidates),
        candidates[0][1],
    )
    return candidates[0][1]


def resolve_categories(constellation: str | None, groups: set[str]) -> list[str]:
    cats: set[str] = set()
    if constellation is not None:
        spec = CONSTELLATION_BY_SLUG.get(constellation)
        if spec is not None:
            if isinstance(spec.category, tuple):
                cats.update(c.value for c in spec.category)
            else:
                cats.add(spec.category.value)
    for group in groups:
        cat = GROUP_TO_CATEGORY.get(group)
        if cat is not None:
            cats.add(cat.value)
    return sorted(cats)


def resolve_operator_qids(
    owner: str | None,
    constellation: str | None,
    launch_date: str | None = None,
    decay_date: str | None = None,
) -> list[str]:
    qids: set[str] = set()
    if owner is not None:
        op = OPERATOR_BY_SOURCE.get(owner)
        if op is not None and op.wikidata_qid is not None:
            if operator_overlaps(op, launch_date, decay_date):
                qids.add(op.wikidata_qid)
    if constellation is not None:
        for op in OPERATOR_BY_CONSTELLATION.get(constellation, ()):
            if op.wikidata_qid is not None:
                if operator_overlaps(op, launch_date, decay_date):
                    qids.add(op.wikidata_qid)
    return sorted(qids)


def resolve_manufacturer_qids(
    constellation: str | None, name: str | None = None
) -> list[str]:
    """QIDs of primes that build hardware for this sat.

    Two paths: constellation slug (Starlink, GPS III, ...) and the resolved
    satellite bus, whose manufacturer applies to every sat on that bus. The bus
    path uses the same word-boundary matcher as ``resolve_bus_slug``, so a sat
    that gets a bus always gets its bus's manufacturer.
    """
    qids: set[str] = set()
    if constellation is not None:
        for mfr in MANUFACTURER_BY_CONSTELLATION.get(constellation, ()):
            if mfr.wikidata_qid is not None:
                qids.add(mfr.wikidata_qid)
    if name is not None:
        bus = bus_for_satellite(name)
        if bus is not None and bus.manufacturer.wikidata_qid is not None:
            qids.add(bus.manufacturer.wikidata_qid)
    return sorted(qids)


def resolve_bus_slug(name: str | None) -> str | None:
    """Match OBJECT_NAME to a satellite bus slug (legacy GEO sats, mostly)."""
    if name is None:
        return None
    bus = bus_for_satellite(name)
    return bus.slug if bus is not None else None


def resolve_country_codes(owner: str | None) -> list[str]:
    if owner is None:
        return []
    source = SOURCE_BY_CODE.get(owner)
    if source is None:
        return []
    return list(source.countries)


# ---------------------------------------------------------------------------
# SATCAT row parsing
# ---------------------------------------------------------------------------


def parse_satcat_fields(sat: dict[str, str]) -> dict:
    """Parse a raw satcat.csv row into typed fields for the Satcat model."""
    orbit_center, docked_to = parse_orbit_center(sat["ORBIT_CENTER"])
    launch_site_code = string_or_none(sat["LAUNCH_SITE"])
    if launch_site_code is not None and launch_site_code not in LAUNCH_SITE_CODES:
        raise ValueError(f"Unknown SATCAT LAUNCH_SITE code: {launch_site_code!r}")
    return dict(
        object_type=parse_object_type(sat["OBJECT_TYPE"]),
        ops_status=parse_ops_status(sat["OPS_STATUS_CODE"]),
        owner=parse_source(sat["OWNER"]),
        launch_date=string_or_none(sat["LAUNCH_DATE"]),
        launch_site_code=launch_site_code,
        decay_date=string_or_none(sat["DECAY_DATE"]),
        period=float_or_none(sat["PERIOD"]),
        apogee=float_or_none(sat["APOGEE"]),
        perigee=float_or_none(sat["PERIGEE"]),
        rcs=float_or_none(sat["RCS"]),
        data_status=parse_data_status(sat["DATA_STATUS_CODE"]),
        orbit_center=orbit_center,
        orbit_center_docked_to=docked_to,
        orbit_type=parse_orbit_type(sat["ORBIT_TYPE"]),
    )
