"""Ingest manually resolved Wikidata QID conflicts from resolved_conflicts.csv."""

import csv
import logging
from pathlib import Path

from sqlalchemy import update

from space_map_data.models.object import Object
from space_map_data.utils.db import get_session
from tqdm import tqdm

logger = logging.getLogger(__name__)

BATCH = 1000


def ingest(download_dir: Path) -> None:
    csv_path = (
        download_dir
        / "sources"
        / "metadata"
        / "wikidata"
        / "ids"
        / "conflicts"
        / "resolved_conflicts.csv"
    )
    if not csv_path.exists():
        return

    session = get_session()
    updated = 0

    with open(csv_path) as f:
        rows = list(csv.reader(f))

    for row in tqdm(rows, desc="Wikidata IDs resolution"):
        if not row or len(row) < 2:
            continue
        object_id, qid = row[0].strip(), row[1].strip()
        if not object_id or not qid:
            continue

        session.execute(
            update(Object).where(Object.id == object_id).values(wikidata_qid=qid)
        )
        updated += 1

        if updated % BATCH == 0:
            session.commit()

    session.commit()

    logger.info(
        "Wikidata conflicts: %d objects updated from resolved_conflicts.csv", updated
    )
