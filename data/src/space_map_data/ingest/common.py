"""Ingest downloaded CSV sources into a unified SQLite database."""

import logging
import time
from pathlib import Path

from sqlalchemy import func

from space_map_data.models.object import Object
from space_map_data.ingest.providers import iau_nomenclature, images
from space_map_data.ingest.providers.objects import (
    celestrak,
    horizons,
    satcat,
    sbdb,
    spice,
)
from space_map_data.ingest.providers.wikidata import (
    nomenclature,
    objects,
    objects_conflicts,
)
from space_map_data.utils.db import get_session

logger = logging.getLogger(__name__)


def ingest_objects(download_dir: Path) -> None:
    """Ingest orbital bodies: SBDB, CelesTrak, SPICE, Horizons."""
    sbdb.ingest(download_dir)
    satcat.ingest(download_dir)
    celestrak.ingest(download_dir)
    spice.ingest(download_dir)
    horizons.ingest(download_dir)


def ingest_features(download_dir: Path) -> None:
    """Ingest surface features (IAU nomenclature)."""
    iau_nomenclature.ingest(download_dir)


def ingest_wikidata(download_dir: Path) -> None:
    """Ingest Wikidata QIDs for objects and features."""
    objects.ingest(download_dir)
    objects_conflicts.ingest(download_dir)
    nomenclature.ingest(download_dir)


def ingest_images() -> None:
    """Set ``image_available`` on every Object from downloaded Commons metadata.

    Must run after ``ingest_wikidata`` so every Object's ``wikidata_qid`` is in
    place — the availability check joins on QID.
    """
    images.ingest()


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


def ingest(download_dir: Path) -> None:
    """Rebuild SQLite DB from downloaded CSVs. Idempotent (drops & recreates)."""
    ingest_objects(download_dir)
    ingest_features(download_dir)
    ingest_wikidata(download_dir)
    ingest_images()
    log_db_summary()
    logger.info("Database ready.")
