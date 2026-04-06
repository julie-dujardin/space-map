"""Ingest Wikidata QID mappings from ids/*.csv into objects.

Reads per-property CSV files produced by the downloader, resolves each
search term to a database object, and sets ``wikidata_qid`` where the
mapping is unambiguous (1 object ↔ 1 QID).  Ambiguous cases are written
to ``ids/ambiguous.csv`` for manual review.
"""

import csv
import io
import logging
from collections import defaultdict
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


def _read_ids_csv(csv_path: Path) -> dict[str, list[str]]:
    """Read a property CSV into a {search_term: [qids]} mapping."""
    mapping: dict[str, list[str]] = {}
    for row in csv.reader(io.StringIO(csv_path.read_text())):
        if not row:
            continue
        search_term = row[0]
        qids = row[1].split() if len(row) > 1 and row[1] else []
        mapping[search_term] = qids
    return mapping


def _build_mappings(
    session, ids_dir: Path
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Build bidirectional object_id ↔ QID mappings from all CSV files.

    Returns (obj_to_qids, qid_to_objs) where both map to sets.
    """
    obj_to_qids: dict[str, set[str]] = defaultdict(set)
    qid_to_objs: dict[str, set[str]] = defaultdict(set)

    # Process property-based CSVs
    for csv_path in ids_dir.glob("P*.csv"):
        pid = csv_path.stem
        if pid not in PID_TO_COLUMN:
            logger.debug("Skipping unknown PID %s", pid)
            continue

        column, converter = PID_TO_COLUMN[pid]
        id_to_qids = _read_ids_csv(csv_path)

        # Batch-lookup: convert search terms and find matching objects
        converted: dict = {}  # converted_value → [qids]
        for search_term, qids in id_to_qids.items():
            if not qids:
                continue
            try:
                key = converter(search_term)
            except (ValueError, TypeError):
                continue
            converted.setdefault(key, []).extend(qids)

        if not converted:
            continue

        # Query DB in batches
        keys = list(converted.keys())
        for i in range(0, len(keys), BATCH):
            batch_keys = keys[i : i + BATCH]
            rows = session.query(Object.id, column).filter(column.in_(batch_keys)).all()
            for obj_id, col_value in rows:
                for qid in converted.get(col_value, []):
                    obj_to_qids[obj_id].add(qid)
                    qid_to_objs[qid].add(obj_id)

    # Process name-based CSV
    name_csv = ids_dir / "name.csv"
    if name_csv.exists():
        name_to_qids = _read_ids_csv(name_csv)
        names = [n for n, qids in name_to_qids.items() if qids]

        for i in range(0, len(names), BATCH):
            batch_names = names[i : i + BATCH]
            rows = (
                session.query(Object.id, Object.name)
                .filter(Object.name.in_(batch_names))
                .all()
            )
            for obj_id, name in rows:
                for qid in name_to_qids.get(name, []):
                    obj_to_qids[obj_id].add(qid)
                    qid_to_objs[qid].add(obj_id)

    return dict(obj_to_qids), dict(qid_to_objs)


def _insert_unambiguous(
    session,
    obj_to_qids: dict[str, set[str]],
    qid_to_objs: dict[str, set[str]],
    *,
    limit: int | None = None,
) -> int:
    """Set wikidata_qid for strict 1-to-1 mappings. Returns update count."""
    updated = 0
    pending = 0

    for obj_id, qids in tqdm(obj_to_qids.items(), desc="wikipedia IDs"):  # noqa: F821
        if limit is not None and updated >= limit:
            break
        if len(qids) != 1:
            continue
        (qid,) = qids
        if len(qid_to_objs.get(qid, set())) != 1:
            continue

        session.execute(
            update(Object)
            .where(Object.id == obj_id, Object.wikidata_qid.is_(None))
            .values(wikidata_qid=qid)
        )
        updated += 1
        pending += 1

        if pending >= BATCH:
            session.commit()
            pending = 0

    if pending:
        session.commit()
    return updated


def _write_ambiguous(
    ids_dir: Path,
    obj_to_qids: dict[str, set[str]],
    qid_to_objs: dict[str, set[str]],
) -> None:
    """Write two ambiguity files:

    - ``multi_objects_per_qid.csv``: ``qid,obj1 obj2 ...``
      One QID matched multiple objects — need to pick which one.
    - ``multi_qids_per_object.csv``: ``obj_id,qid1 qid2 ...``
      One object matched multiple QIDs — need to pick which one.
    """
    # QID → multiple objects
    multi_obj_buf = io.StringIO()
    multi_obj_writer = csv.writer(multi_obj_buf)
    multi_obj_count = 0
    for qid, obj_ids in sorted(qid_to_objs.items()):
        if len(obj_ids) > 1:
            multi_obj_writer.writerow([qid, " ".join(sorted(obj_ids))])
            multi_obj_count += 1

    # Object → multiple QIDs
    multi_qid_buf = io.StringIO()
    multi_qid_writer = csv.writer(multi_qid_buf)
    multi_qid_count = 0
    for obj_id, qids in sorted(obj_to_qids.items()):
        if len(qids) > 1:
            multi_qid_writer.writerow([obj_id, " ".join(sorted(qids))])
            multi_qid_count += 1

    if multi_obj_count:
        (ids_dir / "multi_objects_per_qid.csv").write_text(multi_obj_buf.getvalue())
        logger.info(
            "%d QIDs matched multiple objects → ids/multi_objects_per_qid.csv",
            multi_obj_count,
        )
    if multi_qid_count:
        (ids_dir / "multi_qids_per_object.csv").write_text(multi_qid_buf.getvalue())
        logger.info(
            "%d objects matched multiple QIDs → ids/multi_qids_per_object.csv",
            multi_qid_count,
        )


def ingest(download_dir: Path, *, limit: int | None = None) -> None:
    ids_dir = download_dir / PROVIDERS.WIKIDATA / "ids"
    if not ids_dir.exists():
        logger.warning("Wikidata ids/ not found at %s, skipping", ids_dir)
        return

    session = get_session()
    session.execute(update(Object).values(wikidata_qid=None))
    session.commit()

    obj_to_qids, qid_to_objs = _build_mappings(session, ids_dir)
    logger.info(
        "Wikidata mappings: %d objects, %d QIDs",
        len(obj_to_qids),
        len(qid_to_objs),
    )

    inserted = _insert_unambiguous(session, obj_to_qids, qid_to_objs, limit=limit)
    _write_ambiguous(ids_dir, obj_to_qids, qid_to_objs)

    logger.info("Wikidata ingest: %d objects updated", inserted)
