"""Ingest Wikidata QID mappings from P2824.csv into features.

Reads the P2824 CSV (IAU feature ID → QID) produced by the downloader
and sets ``wikidata_qid`` where the mapping is unambiguous (1 feature ↔ 1 QID).
"""

import csv
import io
import logging
from collections import defaultdict
from pathlib import Path

from sqlalchemy import update

from space_map_data.constants.providers import PROVIDERS
from space_map_data.models.feature import Feature
from space_map_data.utils.db import get_session
from tqdm import tqdm

logger = logging.getLogger(__name__)

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


def ingest(download_dir: Path) -> None:
    ids_dir = download_dir / PROVIDERS.WIKIDATA / "ids"
    csv_path = ids_dir / "P2824.csv"
    if not csv_path.exists():
        logger.warning("Wikidata P2824.csv not found at %s, skipping", csv_path)
        return

    session = get_session()
    session.execute(update(Feature).values(wikidata_qid=None))
    session.commit()

    id_to_qids = _read_ids_csv(csv_path)

    # Build bidirectional mappings: feature_id ↔ QID
    feat_to_qids: dict[int, set[str]] = defaultdict(set)
    qid_to_feats: dict[str, set[int]] = defaultdict(set)

    for search_term, qids in id_to_qids.items():
        if not qids:
            continue
        try:
            feature_id = int(search_term)
        except (ValueError, TypeError):
            continue
        for qid in qids:
            feat_to_qids[feature_id].add(qid)
            qid_to_feats[qid].add(feature_id)

    logger.info(
        "Wikidata feature mappings: %d features, %d QIDs",
        len(feat_to_qids),
        len(qid_to_feats),
    )

    # Set wikidata_qid for strict 1-to-1 mappings
    updated = 0
    pending = 0

    for feature_id, qids in tqdm(feat_to_qids.items(), desc="feature wikidata IDs"):
        if len(qids) != 1:
            continue
        (qid,) = qids
        if len(qid_to_feats.get(qid, set())) != 1:
            continue

        session.execute(
            update(Feature)
            .where(Feature.feature_id == feature_id)
            .values(wikidata_qid=qid)
        )
        updated += 1
        pending += 1

        if pending >= BATCH:
            session.commit()
            pending = 0

    if pending:
        session.commit()

    skipped_multi_qid = sum(1 for qids in feat_to_qids.values() if len(qids) > 1)
    skipped_multi_feat = sum(1 for feats in qid_to_feats.values() if len(feats) > 1)
    if skipped_multi_qid:
        logger.info("  %d features matched multiple QIDs (skipped)", skipped_multi_qid)
    if skipped_multi_feat:
        logger.info("  %d QIDs matched multiple features (skipped)", skipped_multi_feat)

    logger.info("Wikidata feature ingest: %d features updated", updated)
