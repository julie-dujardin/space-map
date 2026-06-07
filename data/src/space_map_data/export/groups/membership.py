"""Group membership inverted index: per-zone {slug: [object_id, ...]}.

Static across snapshots — keyed by stable object id, not row position — so
one file per zone suffices. Frontend fetches it only when a /g/<slug> page
is active, then intersects with whatever positions are currently loaded.
Phase 1 only emits constellation memberships for earth sats.
"""

import gzip
import logging
from pathlib import Path

import orjson
from sqlalchemy import func
from sqlalchemy.orm import Session

from space_map_data.models.object import Object, ObjectType
from space_map_data.models.object.satcat import Satcat

logger = logging.getLogger(__name__)

_EARTH_OBJECT_ID = "naif-399"
_SAT_TYPE_VALUES = [ObjectType.spacecraft.value, ObjectType.debris.value]


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


def build_earth_earliest_launches(session: Session) -> dict[str, str]:
    """Min launch_date per constellation slug, as ISO ``YYYY-MM-DD`` strings.

    Same filter as ``build_earth_membership``; rows without a launch_date are
    skipped by the IS NOT NULL guard so a single dateless member doesn't drag
    the group's start to None.
    """
    rows = (
        session.query(
            Satcat.constellation_slug, func.min(Satcat.launch_date).label("first")
        )
        .join(Object.satcat)
        .filter(
            Object.spkid.is_(None),
            Object.object_type.in_(_SAT_TYPE_VALUES),
            Object.parent_id == _EARTH_OBJECT_ID,
            Satcat.constellation_slug.is_not(None),
            Satcat.launch_date.is_not(None),
        )
        .group_by(Satcat.constellation_slug)
        .all()
    )
    return {slug: first for slug, first in rows if first}


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
