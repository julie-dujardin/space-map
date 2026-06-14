"""Group membership inverted index: per-zone {slug: [object_id, ...]}.

Static across snapshots — keyed by stable object id, not row position — so
one file per zone suffices. Frontend fetches it only when a /g/<slug> page
is active, then intersects with whatever positions are currently loaded.
A single SATCAT scan emits the constellation, operator and launch-site
groupings together to keep the export cheap.
"""

import gzip
import logging
from dataclasses import dataclass, field
from pathlib import Path

import orjson
from sqlalchemy.orm import Session

from space_map_data.constants.countries import COUNTRY_BY_CODE
from space_map_data.constants.earth_sats.launch_sites import LAUNCH_SITE_BY_CODE
from space_map_data.constants.earth_sats.manufacturers import MANUFACTURER_BY_QID
from space_map_data.constants.earth_sats.operators import OPERATOR_BY_QID
from space_map_data.constants.earth_sats.satcat import OpsStatus
from space_map_data.export.groups.registry import (
    BUS_SLUG_PREFIX,
    COUNTRY_SLUG_PREFIX,
    LAUNCH_SITE_SLUG_PREFIX,
    MANUFACTURER_SLUG_PREFIX,
    OPERATOR_SLUG_PREFIX,
    GroupType,
)
from space_map_data.models.object import Object, ObjectType
from space_map_data.models.object.satcat import Satcat

logger = logging.getLogger(__name__)

_EARTH_OBJECT_ID = "naif-399"
_SAT_TYPE_VALUES = [ObjectType.spacecraft.value, ObjectType.debris.value]
_ACTIVE_OPS_STATUSES = {
    OpsStatus.OPERATIONAL.value,
    OpsStatus.PARTIAL.value,
    OpsStatus.EXTENDED_MISSION.value,
}


@dataclass
class GroupSatcatStats:
    """Per-group SATCAT roll-up consumed by the group bundle.

    ``decayed`` and ``active`` are mutually exclusive: ``decay_date`` wins
    even if ``ops_status`` still says operational (data lag).
    """

    launch_histogram: dict[int, int] = field(default_factory=dict)
    active: int = 0
    decayed: int = 0
    launch_sites: dict[str, int] = field(default_factory=dict)
    constellations: dict[str, int] = field(default_factory=dict)
    orbit_classes: dict[str, int] = field(default_factory=dict)
    first_launch_date: str | None = None


@dataclass
class GroupTierBuild:
    """Per-type membership + stats produced from a single SATCAT scan."""

    membership: dict[GroupType, dict[str, list[str]]] = field(default_factory=dict)
    stats: dict[GroupType, dict[str, GroupSatcatStats]] = field(default_factory=dict)

    def add(self, group_type: GroupType, slug: str, obj_id: str) -> GroupSatcatStats:
        self.membership.setdefault(group_type, {}).setdefault(slug, []).append(obj_id)
        return self.stats.setdefault(group_type, {}).setdefault(
            slug, GroupSatcatStats()
        )


def build_earth_groups_data(session: Session) -> GroupTierBuild:
    """Build membership + stats for every earth-sat group type in one scan.

    Mirrors the ``_run_earth_zones`` filter so the row set matches the
    positions shipped in the earth zone. Skips malformed launch dates with
    a warning rather than crashing.
    """
    rows = (
        session.query(
            Object.id,
            Satcat.constellation_slug,
            Satcat.operator_qids,
            Satcat.manufacturer_qids,
            Satcat.bus_slug,
            Satcat.launch_site_code,
            Satcat.country_codes,
            Satcat.launch_date,
            Satcat.ops_status,
            Satcat.decay_date,
        )
        .join(Object.satcat)
        .filter(
            Object.spkid.is_(None),
            Object.object_type.in_(_SAT_TYPE_VALUES),
            Object.parent_id == _EARTH_OBJECT_ID,
        )
        .all()
    )

    build = GroupTierBuild()
    unknown_operator_qids: set[str] = set()
    unknown_manufacturer_qids: set[str] = set()
    unknown_country_codes: set[str] = set()
    for (
        obj_id,
        c_slug,
        op_qids,
        mfr_qids,
        bus_slug,
        site_code,
        country_codes,
        launch_date,
        ops_status,
        decay_date,
    ) in rows:
        slugs: list[tuple[GroupType, str]] = []
        if c_slug:
            slugs.append((GroupType.CONSTELLATION, c_slug))
        if bus_slug:
            slugs.append((GroupType.BUS, f"{BUS_SLUG_PREFIX}{bus_slug}"))
        for qid in op_qids or ():
            op = OPERATOR_BY_QID.get(qid)
            if op is None:
                unknown_operator_qids.add(qid)
                continue
            slugs.append((GroupType.OPERATOR, f"{OPERATOR_SLUG_PREFIX}{op.slug}"))
        for qid in mfr_qids or ():
            mfr = MANUFACTURER_BY_QID.get(qid)
            if mfr is None:
                unknown_manufacturer_qids.add(qid)
                continue
            slugs.append(
                (GroupType.MANUFACTURER, f"{MANUFACTURER_SLUG_PREFIX}{mfr.slug}")
            )
        if site_code:
            site = LAUNCH_SITE_BY_CODE.get(site_code)
            if site is not None:
                slugs.append(
                    (GroupType.LAUNCH_SITE, f"{LAUNCH_SITE_SLUG_PREFIX}{site.slug}")
                )
        for code in country_codes or ():
            country = COUNTRY_BY_CODE.get(code)
            if country is None:
                unknown_country_codes.add(code)
                continue
            slugs.append((GroupType.COUNTRY, f"{COUNTRY_SLUG_PREFIX}{country.slug}"))

        for group_type, group_slug in slugs:
            stats = build.add(group_type, group_slug, obj_id)
            _accumulate(stats, launch_date, ops_status, decay_date, site_code, c_slug)

    for group_type, mem in build.membership.items():
        for ids in mem.values():
            ids.sort()
        logger.info(
            "Built %s membership: %d groups, %d tags",
            group_type.value,
            len(mem),
            sum(len(ids) for ids in mem.values()),
        )
    if unknown_operator_qids:
        logger.warning(
            "Dropped %d unknown operator QID(s) during group build: %s",
            len(unknown_operator_qids),
            sorted(unknown_operator_qids),
        )
    if unknown_manufacturer_qids:
        logger.warning(
            "Dropped %d unknown manufacturer QID(s) during group build: %s",
            len(unknown_manufacturer_qids),
            sorted(unknown_manufacturer_qids),
        )
    if unknown_country_codes:
        logger.warning(
            "Dropped %d unknown country code(s) during group build: %s",
            len(unknown_country_codes),
            sorted(unknown_country_codes),
        )
    return build


def _accumulate(
    stats: GroupSatcatStats,
    launch_date: str | None,
    ops_status: str | None,
    decay_date: str | None,
    site_code: str | None,
    constellation_slug: str | None,
) -> None:
    if launch_date:
        try:
            year = int(launch_date[:4])
        except ValueError:
            logger.warning("Malformed launch_date %r", launch_date)
        else:
            stats.launch_histogram[year] = stats.launch_histogram.get(year, 0) + 1
            if stats.first_launch_date is None or launch_date < stats.first_launch_date:
                stats.first_launch_date = launch_date
    if decay_date:
        stats.decayed += 1
    elif ops_status in _ACTIVE_OPS_STATUSES:
        stats.active += 1
    if site_code:
        stats.launch_sites[site_code] = stats.launch_sites.get(site_code, 0) + 1
    if constellation_slug:
        stats.constellations[constellation_slug] = (
            stats.constellations.get(constellation_slug, 0) + 1
        )


def write_earth_membership(
    out_dir: Path, membership_by_type: dict[GroupType, dict[str, list[str]]]
) -> None:
    """Write one gzipped inverted index merging all earth-sat group types.

    Group slugs are globally unique across types (constellation slugs are
    bare, operator slugs ``op-*``, launch-site slugs ``site-*``, manufacturer
    slugs ``mfr-*``) so a single flat file resolves any /g/<slug> page.
    """
    merged: dict[str, list[str]] = {
        slug: ids for mem in membership_by_type.values() for slug, ids in mem.items()
    }

    path = out_dir / "membership" / "earth.json.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(orjson.dumps(merged)))
    total = sum(len(ids) for ids in merged.values())
    logger.info(
        "Wrote earth membership: %d groups, %d sat-tags, %d bytes gzipped",
        len(merged),
        total,
        path.stat().st_size,
    )
