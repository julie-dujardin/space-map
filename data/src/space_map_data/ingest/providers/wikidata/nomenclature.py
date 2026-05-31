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
from space_map_data.ingest.providers.wikidata.csv_io import read_ids_csv
from space_map_data.models.feature import Feature
from space_map_data.utils.db import get_session
from tqdm import tqdm

logger = logging.getLogger(__name__)

BATCH = 1000


def _read_conflict_resolution(csv_path: Path) -> dict[int, str]:
    """Read the manual conflict-resolution CSV into a {feature_id: qid} mapping."""
    resolutions: dict[int, str] = {}
    for row in csv.reader(io.StringIO(csv_path.read_text())):
        if not row or len(row) < 2:
            continue
        try:
            resolutions[int(row[0])] = row[1].strip()
        except (ValueError, TypeError):
            continue
    return resolutions


def ingest(download_dir: Path) -> None:
    ids_dir = download_dir / PROVIDERS.WIKIDATA / "ids"
    csv_path = ids_dir / "matches" / "P2824.csv"
    if not csv_path.exists():
        logger.warning("Wikidata P2824.csv not found at %s, skipping", csv_path)
        return

    conflict_csv = (
        download_dir / "iau_nomenclature" / "wikipedia_qid_conflict_resolution.csv"
    )
    overrides = _read_conflict_resolution(conflict_csv) if conflict_csv.exists() else {}
    if overrides:
        logger.info(
            "Loaded %d conflict resolutions from %s", len(overrides), conflict_csv
        )

    session = get_session()
    session.execute(update(Feature).values(wikidata_qid=None))
    session.commit()

    id_to_qids = read_ids_csv(csv_path)

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

    # Set wikidata_qid for strict 1-to-1 mappings, using overrides for conflicts
    updated = 0
    pending = 0

    for feature_id, qids in tqdm(feat_to_qids.items(), desc="feature wikidata IDs"):
        qid: str | None = None

        if feature_id in overrides:
            qid = overrides[feature_id]
        elif len(qids) == 1:
            (candidate,) = qids
            if len(qid_to_feats.get(candidate, set())) == 1:
                qid = candidate
            else:
                logger.info(
                    "  QID %s matched multiple features (skipped): %s",
                    candidate,
                    qid_to_feats.get(candidate),
                )
        else:
            logger.info(
                "  feature %d matched multiple QIDs (skipped): %s", feature_id, qids
            )

        if qid is None:
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

    logger.info("Wikidata feature ingest: %d features updated", updated)
