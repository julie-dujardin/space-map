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

from space_map_data.ingest.providers.wikidata.csv_io import read_ids_csv
from space_map_data.models.object import Object, OrbitalSource
from space_map_data.models.object.satcat import Satcat
from space_map_data.utils.db import get_session
from tqdm import tqdm

logger = logging.getLogger(__name__)

# Wikidata property ID → list of (Object column, value converter)
PID_TO_COLUMNS = {
    "P2956": [(Object.naif_id, int)],
    "P716": [(Object.spkid, int)],
    "P5736": [
        (Object.mpc_designation, str),
        (Object.provisional_designation, str),
    ],
    "P377": [(Object.norad_cat_id, int)],
    "P247": [(Object.cospar_id, str)],
    "P490": [(Object.provisional_designation, str)],
}

BATCH = 1000


def _build_mappings(
    session, ids_dir: Path
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Build bidirectional object_id ↔ QID mappings from all CSV files.

    Returns (obj_to_qids, qid_to_objs) where both map to sets.
    """
    obj_to_qids: dict[str, set[str]] = defaultdict(set)
    qid_to_objs: dict[str, set[str]] = defaultdict(set)

    # Process property-based CSVs
    matches_dir = ids_dir / "matches"
    for csv_path in matches_dir.glob("P*.csv"):
        pid = csv_path.stem
        if pid not in PID_TO_COLUMNS:
            logger.debug("Skipping unknown PID %s", pid)
            continue

        id_to_qids = read_ids_csv(csv_path)

        for column, converter in PID_TO_COLUMNS[pid]:
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
                rows = (
                    session.query(Object.id, column)
                    .filter(column.in_(batch_keys))
                    .all()
                )
                for obj_id, col_value in rows:
                    for qid in converted.get(col_value, []):
                        obj_to_qids[obj_id].add(qid)
                        qid_to_objs[qid].add(obj_id)

    # Process name-based CSV
    name_csv = matches_dir / "name.csv"
    if name_csv.exists():
        name_to_qids = read_ids_csv(name_csv)
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
) -> int:
    """Set wikidata_qid for strict 1-to-1 mappings. Returns update count."""
    updated = 0
    pending = 0

    for obj_id, qids in tqdm(obj_to_qids.items(), desc="wikipedia IDs"):
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

    conflicts_dir = ids_dir / "conflicts"
    conflicts_dir.mkdir(exist_ok=True)
    if multi_obj_count:
        (conflicts_dir / "multi_objects_per_qid.csv").write_text(
            multi_obj_buf.getvalue()
        )
        logger.info(
            "%d QIDs matched multiple objects → ids/conflicts/multi_objects_per_qid.csv",
            multi_obj_count,
        )
    if multi_qid_count:
        (conflicts_dir / "multi_qids_per_object.csv").write_text(
            multi_qid_buf.getvalue()
        )
        logger.info(
            "%d objects matched multiple QIDs → ids/conflicts/multi_qids_per_object.csv",
            multi_qid_count,
        )


# Wikidata property ID → list of (Satcat column, value converter)
PID_TO_SATCAT_COLUMNS = {
    "P377": [(Satcat.NORAD_CAT_ID, int)],
    "P247": [(Satcat.COSPAR_ID, str)],
}


def _build_satcat_mappings(
    session, ids_dir: Path
) -> tuple[dict[int, set[str]], dict[str, set[int]]]:
    """Build bidirectional NORAD_CAT_ID ↔ QID mappings for Satcat rows.

    Returns (norad_to_qids, qid_to_norads).
    """
    norad_to_qids: dict[int, set[str]] = defaultdict(set)
    qid_to_norads: dict[str, set[int]] = defaultdict(set)

    matches_dir = ids_dir / "matches"
    for csv_path in matches_dir.glob("P*.csv"):
        pid = csv_path.stem
        if pid not in PID_TO_SATCAT_COLUMNS:
            continue

        id_to_qids = read_ids_csv(csv_path)

        for column, converter in PID_TO_SATCAT_COLUMNS[pid]:
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

            # Query Satcat in batches — join via NORAD_CAT_ID
            keys = list(converted.keys())
            for i in range(0, len(keys), BATCH):
                batch_keys = keys[i : i + BATCH]
                rows = (
                    session.query(Satcat.NORAD_CAT_ID, column)
                    .filter(column.in_(batch_keys))
                    .all()
                )
                for norad_id, col_value in rows:
                    for qid in converted.get(col_value, []):
                        norad_to_qids[norad_id].add(qid)
                        qid_to_norads[qid].add(norad_id)

    return dict(norad_to_qids), dict(qid_to_norads)


def _insert_satcat_unambiguous(
    session,
    norad_to_qids: dict[int, set[str]],
    qid_to_norads: dict[str, set[int]],
) -> int:
    """Set Satcat.wikidata_qid for strict 1-to-1 mappings. Returns update count."""
    updated = 0
    pending = 0

    for norad_id, qids in tqdm(norad_to_qids.items(), desc="satcat wikipedia IDs"):
        if len(qids) != 1:
            continue
        (qid,) = qids
        if len(qid_to_norads.get(qid, set())) != 1:
            continue

        session.execute(
            update(Satcat)
            .where(Satcat.NORAD_CAT_ID == norad_id, Satcat.wikidata_qid.is_(None))
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


def ingest(download_dir: Path) -> None:
    ids_dir = download_dir / "sources" / "metadata" / "wikidata" / "ids"
    if not ids_dir.exists():
        logger.warning("Wikidata ids/ not found at %s, skipping", ids_dir)
        return

    session = get_session()
    # Probes carry hand-curated QIDs (no Wikidata external ID property to
    # SPARQL them through), so they're excluded from the wipe.
    session.execute(
        update(Object)
        .where(Object.orbital_source != OrbitalSource.spice_probe)
        .values(wikidata_qid=None)
    )
    session.commit()

    obj_to_qids, qid_to_objs = _build_mappings(session, ids_dir)
    logger.info(
        "Wikidata mappings: %d objects, %d QIDs",
        len(obj_to_qids),
        len(qid_to_objs),
    )

    inserted = _insert_unambiguous(session, obj_to_qids, qid_to_objs)
    _write_ambiguous(ids_dir, obj_to_qids, qid_to_objs)
    logger.info("Wikidata ingest: %d objects updated", inserted)

    # Satcat QID matching (covers all ~65k SATCAT entries)
    session.execute(update(Satcat).values(wikidata_qid=None))
    session.commit()

    norad_to_qids, qid_to_norads = _build_satcat_mappings(session, ids_dir)
    logger.info(
        "Wikidata satcat mappings: %d NORAD IDs, %d QIDs",
        len(norad_to_qids),
        len(qid_to_norads),
    )

    satcat_inserted = _insert_satcat_unambiguous(session, norad_to_qids, qid_to_norads)
    logger.info("Wikidata ingest: %d satcat entries updated", satcat_inserted)
