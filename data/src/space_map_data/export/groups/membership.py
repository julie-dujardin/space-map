"""Group membership inverted index: per-zone {slug: [object_id, ...]}.

Static across snapshots — keyed by stable object id, not row position — so
one file per zone suffices. Frontend fetches it only when a /g/<slug> page
is active, then intersects with whatever positions are currently loaded.
Phase 1 only emits constellation memberships for earth sats.
"""

import gzip
import logging
from dataclasses import dataclass, field
from pathlib import Path

import orjson
from sqlalchemy.orm import Session

from space_map_data.constants.earth_sats.satcat import OpsStatus
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
    """Per-constellation roll-up consumed by the group bundle.

    ``decayed`` and ``active`` are mutually exclusive: ``decay_date`` wins
    even if ``ops_status`` still says operational (data lag).
    """

    launch_histogram: dict[int, int] = field(default_factory=dict)
    active: int = 0
    decayed: int = 0
    launch_sites: dict[str, int] = field(default_factory=dict)
    first_launch_date: str | None = None


def build_earth_membership(session: Session) -> dict[str, list[str]]:
    """Build {slug: sorted [object_id]} of constellation memberships.

    Filter mirrors ``_run_earth_zones`` so the same row set ships in
    position files. ``constellation_slug`` is populated at ingest.
    """
    rows = (
        session.query(Object.id, Satcat.constellation_slug)
        .join(Object.satcat)
        .filter(
            Object.spkid.is_(None),
            Object.object_type.in_(_SAT_TYPE_VALUES),
            Object.parent_id == _EARTH_OBJECT_ID,
            Satcat.constellation_slug.is_not(None),
        )
        .all()
    )
    membership: dict[str, list[str]] = {}
    for obj_id, slug in rows:
        membership.setdefault(slug, []).append(obj_id)
    for ids in membership.values():
        ids.sort()
    return membership


def build_earth_group_stats(session: Session) -> dict[str, GroupSatcatStats]:
    """Per-constellation launch histogram, status counts, and launch-site mix.

    Single SATCAT scan; same filter as ``build_earth_membership``. Years
    come from ``launch_date[:4]`` so the rare malformed date is silently
    skipped via ``ValueError`` rather than crashing the export.
    """
    rows = (
        session.query(
            Satcat.constellation_slug,
            Satcat.launch_date,
            Satcat.ops_status,
            Satcat.decay_date,
            Satcat.launch_site_code,
        )
        .join(Object.satcat)
        .filter(
            Object.spkid.is_(None),
            Object.object_type.in_(_SAT_TYPE_VALUES),
            Object.parent_id == _EARTH_OBJECT_ID,
            Satcat.constellation_slug.is_not(None),
        )
        .all()
    )
    stats: dict[str, GroupSatcatStats] = {}
    for slug, launch_date, ops_status, decay_date, site_code in rows:
        s = stats.setdefault(slug, GroupSatcatStats())
        if launch_date:
            try:
                year = int(launch_date[:4])
            except ValueError:
                logger.warning("Malformed launch_date %r for %s", launch_date, slug)
            else:
                s.launch_histogram[year] = s.launch_histogram.get(year, 0) + 1
                if s.first_launch_date is None or launch_date < s.first_launch_date:
                    s.first_launch_date = launch_date
        if decay_date:
            s.decayed += 1
        elif ops_status in _ACTIVE_OPS_STATUSES:
            s.active += 1
        if site_code:
            s.launch_sites[site_code] = s.launch_sites.get(site_code, 0) + 1
    return stats


def write_earth_membership(out_dir: Path, membership: dict[str, list[str]]) -> None:
    """Write the gzipped inverted index."""
    path = out_dir / "membership" / "earth.json.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(orjson.dumps(membership)))
    total = sum(len(ids) for ids in membership.values())
    logger.info(
        "Wrote earth membership: %d groups, %d sat-tags, %d bytes gzipped",
        len(membership),
        total,
        path.stat().st_size,
    )
