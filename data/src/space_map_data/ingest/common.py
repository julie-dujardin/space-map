"""Ingest downloaded CSV sources into a unified SQLite database."""

import logging
import time
from pathlib import Path

from sqlalchemy import func

from space_map_data.ingest.checks import assert_no_namespace_collision
from space_map_data.models.object import Object
from space_map_data.ingest.providers import (
    iau_nomenclature,
    image_selection,
    sitelinks,
    wikipedia,
)
from space_map_data.ingest.providers.objects import (
    celestrak,
    probes,
    satcat,
    sbdb,
    sbdb_moons,
    spice,
)
from space_map_data.ingest.providers.wikidata import (
    comet_fragments,
    nomenclature,
    objects,
    objects_conflicts,
)
from space_map_data.utils.db import get_session

logger = logging.getLogger(__name__)


def ingest_objects(download_dir: Path) -> None:
    """Ingest orbital bodies: SBDB, SPICE, spacecraft.

    Order: naturals first (sbdb → spice → sbdb_moons), then artificial
    earth-sat / spacecraft (satcat → probes → celestrak).

    Kepler elements for natural NAIF-keyed bodies land on the Horizons
    sub-table via SPICE ingest (the table name is historical; SPICE is now
    the only writer).

    Satcat ingests before probes so probe rows can FK their
    `satcat_norad_cat_id` directly against existing satcat rows at insert
    time. CelesTrak runs last so it can claim the celestrak FK on the
    appropriate probe row (or mint `norad_satcat-N` when no probe matches).
    """
    # --- Natural bodies ---
    sbdb.ingest(download_dir)
    spice.ingest(download_dir)
    # sbdb_moons runs after spice so the name-match against Horizons/SPICE
    # moons can find existing rows (e.g. Pluto's Charon) and merge SBDB
    # metadata onto them instead of producing duplicate Object rows.
    sbdb_moons.ingest(download_dir)
    # --- Artificial / earth-sat objects ---
    satcat.ingest(download_dir)
    # Spacecraft Object rows from `missions/*/_index.json`. Their IDs are
    # `probe-<int>` rather than `naif-<int>` because NAIF IDs are recycled.
    # Sets `satcat_norad_cat_id` FK against the satcat table populated above.
    probes.ingest(download_dir)
    celestrak.ingest(download_dir)
    # Post-ingest invariants: probe-* and norad_satcat-* must be disjoint by
    # NORAD + COSPAR, and the FK ↔ denormalized norad_cat_id must agree.
    assert_no_namespace_collision(get_session())


def ingest_features(download_dir: Path) -> None:
    """Ingest surface features (IAU nomenclature)."""
    iau_nomenclature.ingest(download_dir)


def ingest_wikidata(download_dir: Path) -> None:
    """Ingest Wikidata QIDs for objects and features, then sitelink counts.

    Sitelinks run last so every Object's ``wikidata_qid`` is in place.
    """
    objects.ingest(download_dir)
    objects_conflicts.ingest(download_dir)
    # Resolve split-comet parents whose QID was dropped as a family-internal
    # conflict (parent + fragments share the comet number). Runs after the
    # manual conflict pass so it only fills genuinely-unmatched parents.
    comet_fragments.ingest(download_dir)
    nomenclature.ingest(download_dir)
    sitelinks.ingest()


def ingest_images() -> None:
    """Compute the per-object best Commons image and set ``image_available``.

    Writes ``OBJECT_IMAGES_PATH`` keyed by ``Object.id``,
    with at most one filename per derivative-tree component (best by
    assessment > pageimage frequency > globalusage). Sets
    ``Object.image_available`` based on whether any image survives the
    selection.

    Must run after ``ingest_wikidata`` so every Object's ``wikidata_qid`` is
    in place — discovery joins on QID.
    """
    image_selection.ingest()


def ingest_wikipedia() -> None:
    """Set ``Object.has_wikipedia_description`` from downloaded summaries.

    Must run after ``ingest_wikidata`` so every Object's ``wikidata_qid`` is
    in place — the lookup is keyed on QID.
    """
    wikipedia.ingest()


def log_db_summary(start_time: float | None = None) -> None:
    """Log object counts by type, plus elapsed wall-time if start_time is given."""
    session = get_session()
    counts = (
        session.query(Object.object_type, func.count())
        .group_by(Object.object_type)
        .order_by(func.count().desc())
        .all()
    )
    for object_type, cnt in counts:
        logger.info("  %-20s %d", object_type, cnt)
    total = session.query(func.count(Object.id)).scalar()
    logger.info("Total: %d objects", total)
    if start_time is not None:
        logger.info("Elapsed: %.1fs", time.perf_counter() - start_time)
