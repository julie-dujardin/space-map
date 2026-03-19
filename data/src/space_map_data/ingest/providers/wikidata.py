"""Ingest Wikidata id_map.json — updates existing objects with wikidata_qid."""

import json
import logging
from pathlib import Path

from sqlalchemy import update

from space_map_data.constants.providers import PROVIDERS
from space_map_data.models.object import Object
from space_map_data.utils.db import get_session
from tqdm import tqdm

logger = logging.getLogger(__name__)

# Wikidata property ID → (Object column, value converter)
PID_TO_COLUMN = {
    "P2956": (Object.horizons_naif_id, int),
    "P716": (Object.sbdb_spkid, int),
    "P5736": (Object.sbdb_mcp_designation, str),
    "P377": (Object.celestrak_norad_cat_id, int),
    "P247": (Object.celestrak_cospar_id, str),
    "P490": (Object.provisional_designation, str),
}

BATCH = 1000


def _ingest_pid(
    session, pid: str, id_to_qid: dict[str, str], *, limit: int | None = None
) -> int:
    """Update objects matching a single Wikidata property. Returns update count."""
    if pid not in PID_TO_COLUMN:
        logger.warning("Unknown PID %s, skipping", pid)
        return 0

    column, converter = PID_TO_COLUMN[pid]
    updated = 0
    items = list(id_to_qid.items())
    if limit:
        items = items[:limit]

    for i in range(0, len(items), BATCH):
        batch = items[i : i + BATCH]
        # Build a mapping of converted_id → qid for this batch
        id_qid_map = {}
        for source_id, qid in batch:
            try:
                key = converter(source_id)
            except (ValueError, TypeError):
                continue
            # First occurrence wins if multiple source IDs map to the same object
            if key not in id_qid_map:
                id_qid_map[key] = qid

        if not id_qid_map:
            continue

        # Find objects that match and don't already have a wikidata_qid
        matching = (
            session.query(Object.id, column)
            .filter(
                column.in_(list(id_qid_map.keys())),
                Object.wikidata_qid.is_(None),
            )
            .all()
        )

        for obj_id, col_value in matching:
            qid = id_qid_map.get(col_value)
            if qid:
                session.execute(
                    update(Object).where(Object.id == obj_id).values(wikidata_qid=qid)
                )
                updated += 1

        session.commit()

    return updated


def ingest(download_dir: Path, *, limit: int | None = None) -> None:
    id_map_path = download_dir / PROVIDERS.WIKIDATA / "id_map.json"
    if not id_map_path.exists():
        logger.warning("Wikidata id_map.json not found at %s, skipping", id_map_path)
        return

    with open(id_map_path) as f:
        id_map: dict[str, dict[str, str]] = json.load(f)

    session = get_session()
    total = 0

    for pid, id_to_qid in tqdm(
        id_map.items(), total=len(id_map.items()), desc="Wikidata ingest"
    ):
        count = _ingest_pid(session, pid, id_to_qid, limit=limit)
        logger.info("Wikidata %s: updated %d objects", pid, count)
        total += count

    logger.info("Wikidata ingest: %d objects updated total", total)
