"""Ingest downloaded CSV sources into a unified SQLite database."""

import logging
from pathlib import Path

from sqlalchemy import func

from space_map_data.models.object import Object
from space_map_data.ingest.providers import iau_nomenclature
from space_map_data.ingest.providers.objects import celestrak, horizons, sbdb
from space_map_data.ingest.providers.wikidata import (
    nomenclature,
    objects,
    objects_conflicts,
)
from space_map_data.utils.db import get_session

logger = logging.getLogger(__name__)


def ingest_objects(download_dir: Path) -> None:
    """Ingest orbital bodies: SBDB, CelesTrak, Horizons."""
    sbdb.ingest(download_dir)
    celestrak.ingest(download_dir)
    horizons.ingest(download_dir)


def ingest_features(download_dir: Path) -> None:
    """Ingest surface features (IAU nomenclature)."""
    iau_nomenclature.ingest(download_dir)


def ingest_wikidata(download_dir: Path) -> None:
    """Ingest Wikidata QIDs for objects and features."""
    objects.ingest(download_dir)
    objects_conflicts.ingest(download_dir)
    nomenclature.ingest(download_dir)


def log_db_summary() -> None:
    """Log object counts by type."""
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


def ingest(download_dir: Path) -> None:
    """Rebuild SQLite DB from downloaded CSVs. Idempotent (drops & recreates)."""
    ingest_objects(download_dir)
    ingest_features(download_dir)
    ingest_wikidata(download_dir)
    log_db_summary()
    logger.info("Database ready.")
