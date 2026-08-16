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
    jpl_satellite_discovery,
    launch_site,
    launch_vehicle,
    launchlog,
    probes,
    satcat,
    sbdb,
    sbdb_moons,
    spice,
    ssodnet,
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
    earth-sat / spacecraft (satcat → probes → celestrak). Satcat ingests
    before probes so probe rows can FK `satcat_norad_cat_id` at insert time;
    celestrak runs last so it can claim the FK on the matching probe row
    (or mint `norad_satcat-N` when none matches).
    """
    # --- Natural bodies ---
    sbdb.ingest(download_dir)
    spice.ingest(download_dir)
    # After spice so name-matching against Horizons/SPICE moons merges SBDB
    # metadata onto existing rows instead of duplicating them.
    sbdb_moons.ingest(download_dir)
    # Taxonomic classes, keyed on the SPK-IDs sbdb just wrote.
    ssodnet.ingest(download_dir)
    jpl_satellite_discovery.ingest(download_dir)
    # --- Artificial / earth-sat objects ---
    satcat.ingest(download_dir)
    # IDs are `probe-<int>` not `naif-<int>` because NAIF IDs are recycled.
    probes.ingest(download_dir)
    celestrak.ingest(download_dir)
    launch_vehicle.ingest(download_dir)
    launch_site.ingest(download_dir)
    # Runs last so every cospar-bearing Object, including backfilled
    # norad_satcat-* rows, already exists to link against.
    launchlog.ingest(download_dir)
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
    """Pick the best Commons image per object, ranked by assessment >
    pageimage frequency > globalusage, and set ``Object.image_available``.

    Must run after ``ingest_wikidata`` — discovery joins on ``wikidata_qid``.
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
