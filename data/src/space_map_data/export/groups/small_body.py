"""Per-orbit-class and per-flag stats for small-body groups.

No membership inverted index ships for small bodies — orbit class is the
selector and the export already partitions positions by class under
``small_bodies/<class>/``. NEO/PHA flags ride on the per-point ``flags`` byte
of the elements tiles and are filtered render-time on the frontend. Only
aggregate stats are needed in the group bundle.

The filter here mirrors ``_iter_sbdb_zone_snapshots`` in the orchestrator so
stats match the rows that actually ship. Histograms are aggregated
server-side (GROUP BY year derived from ``first_obs``) so the ~1.3M-row
SBDB scan never crosses the ORM boundary.
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from space_map_data.export.groups.registry import (
    CLASS_SLUG_PREFIX,
    SMALL_BODY_FLAG_SLUG_PREFIX,
)
from space_map_data.models.object.main import Object, OrbitalSource
from space_map_data.models.object.sbdb import SBDB, CometPrefix

logger = logging.getLogger(__name__)


@dataclass
class SmallBodyGroupStats:
    """Per-slug member counts and ``first_obs`` year histograms."""

    member_counts: dict[str, int] = field(default_factory=dict)
    discovery_histograms: dict[str, dict[int, int]] = field(default_factory=dict)


def _exported_sbdb_filter():
    """The row-level filter shared with `_iter_sbdb_zone_snapshots`."""
    return (
        SBDB.prefix.is_distinct_from(CometPrefix.D),
        or_(
            Object.orbital_source.is_(None),
            Object.orbital_source == OrbitalSource.sbdb,
        ),
    )


def build_small_body_group_stats(session: Session) -> SmallBodyGroupStats:
    """Return member counts and discovery-year histograms per small-body group.

    All aggregation runs in SQL — the function pulls only summary rows
    (~5k for class×year histograms, ~200 each for NEO/PHA). Rows lacking a
    parseable year are excluded from histograms but still count toward
    ``member_counts``.
    """
    base = (
        session.query(SBDB)
        .join(Object, Object.id == SBDB.object_id)
        .filter(*_exported_sbdb_filter())
    )

    class_counts = (
        base.with_entities(SBDB.class_, func.count(SBDB.spkid))
        .group_by(SBDB.class_)
        .all()
    )
    member_counts: dict[str, int] = {
        f"{CLASS_SLUG_PREFIX}{cls.name}": n for cls, n in class_counts
    }
    neo_count = base.filter(SBDB.neo.is_(True)).count()
    pha_count = base.filter(SBDB.pha.is_(True)).count()
    member_counts[f"{SMALL_BODY_FLAG_SLUG_PREFIX}neo"] = neo_count
    member_counts[f"{SMALL_BODY_FLAG_SLUG_PREFIX}pha"] = pha_count

    year_expr = func.substr(SBDB.first_obs, 1, 4)
    discovery_histograms: dict[str, dict[int, int]] = {}
    malformed_years: set[str] = set()

    def _add(slug: str, year_str: str | None, n: int) -> None:
        if year_str is None:
            return
        try:
            year = int(year_str)
        except ValueError:
            malformed_years.add(year_str)
            return
        hist = discovery_histograms.setdefault(slug, {})
        hist[year] = hist.get(year, 0) + n

    class_year_rows = (
        base.with_entities(SBDB.class_, year_expr, func.count(SBDB.spkid))
        .filter(SBDB.first_obs.is_not(None))
        .group_by(SBDB.class_, year_expr)
        .all()
    )
    for cls, year_str, n in class_year_rows:
        _add(f"{CLASS_SLUG_PREFIX}{cls.name}", year_str, n)

    neo_year_rows = (
        base.with_entities(year_expr, func.count(SBDB.spkid))
        .filter(SBDB.neo.is_(True), SBDB.first_obs.is_not(None))
        .group_by(year_expr)
        .all()
    )
    for year_str, n in neo_year_rows:
        _add(f"{SMALL_BODY_FLAG_SLUG_PREFIX}neo", year_str, n)

    pha_year_rows = (
        base.with_entities(year_expr, func.count(SBDB.spkid))
        .filter(SBDB.pha.is_(True), SBDB.first_obs.is_not(None))
        .group_by(year_expr)
        .all()
    )
    for year_str, n in pha_year_rows:
        _add(f"{SMALL_BODY_FLAG_SLUG_PREFIX}pha", year_str, n)

    missing_first_obs = (
        base.with_entities(func.count(SBDB.spkid))
        .filter(SBDB.first_obs.is_(None))
        .scalar()
        or 0
    )
    if missing_first_obs or malformed_years:
        logger.info(
            "Small-body discovery histograms: %d rows without first_obs, "
            "%d malformed year value(s) excluded: %s",
            missing_first_obs,
            len(malformed_years),
            sorted(malformed_years) if malformed_years else "[]",
        )

    logger.info(
        "Built small-body group stats: %d classes, NEO=%d, PHA=%d, "
        "histograms for %d slugs",
        len(class_counts),
        neo_count,
        pha_count,
        len(discovery_histograms),
    )
    return SmallBodyGroupStats(
        member_counts=member_counts,
        discovery_histograms=discovery_histograms,
    )
