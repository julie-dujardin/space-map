"""Ingest downloaded CSV sources into a unified SQLite database."""

import logging
from pathlib import Path

from sqlalchemy import func

from space_map_data.models.body import Object
from space_map_data.ingest.providers import celestrak, horizons, sbdb
from space_map_data.utils.db import get_session

logger = logging.getLogger(__name__)


def _post_process() -> None:
    """Fill in missing names from SBDB source data and log summary."""
    session = get_session()

    # Summary
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


def ingest(
    download_dir: Path,
    *,
    limit: int | None = None,
) -> None:
    """Rebuild SQLite DB from downloaded CSVs. Idempotent (drops & recreates)."""
    sbdb.ingest(download_dir, limit=limit)
    celestrak.ingest(download_dir, limit=limit)
    horizons.ingest(download_dir, limit=limit)
    _post_process()

    logger.info("Database ready.")
