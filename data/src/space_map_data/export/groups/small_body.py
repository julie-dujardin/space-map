"""Per-orbit-class and per-flag member counts for small-body groups.

No membership inverted index ships for small bodies — orbit class is the
selector and the export already partitions positions by class under
``small_bodies/<class>/``. NEO/PHA flags ride on the per-point ``flags`` byte
of the elements tiles and are filtered render-time on the frontend. Only
aggregate counts are needed in the group bundle.

The filter here mirrors ``_iter_sbdb_zone_snapshots`` in the orchestrator so
counts match the rows that actually ship.
"""

import logging

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from space_map_data.export.groups.registry import (
    CLASS_SLUG_PREFIX,
    SMALL_BODY_FLAG_SLUG_PREFIX,
)
from space_map_data.models.object.main import Object, OrbitalSource
from space_map_data.models.object.sbdb import SBDB, CometPrefix

logger = logging.getLogger(__name__)


def _exported_sbdb_filter():
    """The row-level filter shared with `_iter_sbdb_zone_snapshots`."""
    return (
        SBDB.prefix.is_distinct_from(CometPrefix.D),
        or_(
            Object.orbital_source.is_(None),
            Object.orbital_source == OrbitalSource.sbdb,
        ),
    )


def build_small_body_member_counts(session: Session) -> dict[str, int]:
    """Return ``{slug: count}`` for every orbit class and small-body flag."""
    base = (
        session.query(SBDB)
        .join(Object, Object.id == SBDB.object_id)
        .filter(*_exported_sbdb_filter())
    )
    class_rows = (
        base.with_entities(SBDB.class_, func.count(SBDB.spkid))
        .group_by(SBDB.class_)
        .all()
    )
    counts: dict[str, int] = {
        f"{CLASS_SLUG_PREFIX}{cls.name}": n for cls, n in class_rows
    }
    neo_count = base.filter(SBDB.neo.is_(True)).count()
    pha_count = base.filter(SBDB.pha.is_(True)).count()
    counts[f"{SMALL_BODY_FLAG_SLUG_PREFIX}neo"] = neo_count
    counts[f"{SMALL_BODY_FLAG_SLUG_PREFIX}pha"] = pha_count
    logger.info(
        "Built small-body group counts: %d classes, NEO=%d, PHA=%d",
        len(class_rows),
        neo_count,
        pha_count,
    )
    return counts
