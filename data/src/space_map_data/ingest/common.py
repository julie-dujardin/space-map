"""Ingest downloaded CSV sources into a unified SQLite database."""

import logging
from pathlib import Path

from sqlalchemy import func, update

from space_map_data.models.body import Object, SBDB
from space_map_data.ingest.providers import celestrak, horizons, sbdb
from space_map_data.utils.db import get_session

logger = logging.getLogger(__name__)


def _post_process() -> None:
    """Fill in missing names from SBDB source data and log summary."""
    session = get_session()
    # Objects ingested from SBDB with no IAU name — use full_name or pdes
    sbdb_name = (
        session.query(
            func.coalesce(
                func.nullif(SBDB.name, ""),
                func.nullif(SBDB.full_name, ""),
                func.nullif(SBDB.pdes, ""),
            ),
        )
        .filter(SBDB.object_id == Object.id)
        .correlate(Object)
        .scalar_subquery()
    )
    session.execute(
        update(Object)
        .where(
            Object.sbdb_spkid.isnot(None),
            (Object.name.is_(None)) | (Object.name == ""),
        )
        .values(name=sbdb_name)
    )
    session.commit()

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
