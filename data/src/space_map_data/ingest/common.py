"""Ingest downloaded CSV sources into a unified SQLite database."""

import logging
from pathlib import Path

from sqlalchemy import func

from space_map_data.models.object import Object
from space_map_data.ingest.providers import (
    celestrak,
    horizons,
    iau_nomenclature,
    sbdb,
    wikidata,
    wikidata_conflicts,
)
from space_map_data.utils.db import get_session

logger = logging.getLogger(__name__)


def ingest_bodies(download_dir: Path, *, limit: int | None = None) -> None:
    """Ingest orbital bodies: SBDB, CelesTrak, Horizons, Wikidata."""
    sbdb.ingest(download_dir, limit=limit)
    celestrak.ingest(download_dir, limit=limit)
    horizons.ingest(download_dir, limit=limit)
    wikidata.ingest(download_dir, limit=limit)
    wikidata_conflicts.ingest(download_dir, limit=limit)


def ingest_features(download_dir: Path, *, limit: int | None = None) -> None:
    """Ingest surface features (IAU nomenclature)."""
    iau_nomenclature.ingest(download_dir, limit=limit)


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


def ingest(download_dir: Path, *, limit: int | None = None) -> None:
    """Rebuild SQLite DB from downloaded CSVs. Idempotent (drops & recreates)."""
    ingest_bodies(download_dir, limit=limit)
    ingest_features(download_dir, limit=limit)
    log_db_summary()
    logger.info("Database ready.")
