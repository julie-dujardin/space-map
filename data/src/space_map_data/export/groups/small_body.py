"""Per-orbit-class member counts for small-body groups.

No membership inverted index ships for small bodies — the orbit class is
the selector and the export already partitions positions by class under
``small_bodies/<class>/``. The frontend reads ``sbdb.class`` (or the zone
path) to decide membership, so only an aggregate count is needed for the
group bundle.

The filter here mirrors ``_iter_sbdb_zone_snapshots`` in the orchestrator
so the count matches the rows that actually ship in those zones.
"""

import logging

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from space_map_data.export.groups.registry import CLASS_SLUG_PREFIX
from space_map_data.models.object.main import Object, OrbitalSource
from space_map_data.models.object.sbdb import SBDB, CometPrefix

logger = logging.getLogger(__name__)


def build_small_body_member_counts(session: Session) -> dict[str, int]:
    """Return ``{class-<NAME>: count}`` over every orbit class with rows."""
    rows = (
        session.query(SBDB.class_, func.count(SBDB.spkid))
        .join(Object, Object.id == SBDB.object_id)
        .filter(
            SBDB.prefix.is_distinct_from(CometPrefix.D),
            or_(
                Object.orbital_source.is_(None),
                Object.orbital_source == OrbitalSource.sbdb,
            ),
        )
        .group_by(SBDB.class_)
        .all()
    )
    counts = {f"{CLASS_SLUG_PREFIX}{cls.name}": n for cls, n in rows}
    logger.info(
        "Built small-body group counts: %d classes, %d members total",
        len(counts),
        sum(counts.values()),
    )
    return counts
