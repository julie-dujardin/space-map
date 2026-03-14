"""Ingest downloaded CSV sources into a unified SQLite database."""

import logging
from pathlib import Path

from sqlalchemy import create_engine, func, text, update
from sqlalchemy.orm import Session

from space_map_data.models import Base, Object, SBDB
from space_map_data.ingest.providers import celestrak, horizons, sbdb

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[3]
DOWNLOAD_DIR = DATA_DIR / "downloads"


def _post_process(session: Session) -> None:
    """Fill in missing names from SBDB source data and log summary."""
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
    db_path: Path,
    download_dir: Path,
    *,
    limit: int | None = None,
) -> None:
    """Rebuild SQLite DB from downloaded CSVs. Idempotent (drops & recreates)."""
    logger.info("Building database at %s", db_path)
    db_path.unlink(missing_ok=True)

    engine = create_engine(f"sqlite:///{db_path}", echo=False)

    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.execute(text("PRAGMA synchronous=NORMAL"))
        conn.commit()

    Base.metadata.create_all(engine)

    with Session(engine) as session:
        horizons.ingest(session, download_dir, limit=limit)
        sbdb.ingest(session, download_dir, limit=limit)
        celestrak.ingest(session, download_dir, limit=limit)
        _post_process(session)

    engine.dispose()
    logger.info("Database ready: %s", db_path)
