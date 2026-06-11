"""Set ``Object.sitelinks_count`` from downloaded Wikidata entity JSONs.

Walks ``wikidata/objects/<qid>.json`` for every Object with a Wikidata QID
and persists the raw sitelink count (all Wikimedia projects, matching the
count used by image selection). Reset-then-set like the ``image_available``
and ``has_wikipedia_description`` passes, so removals are reflected too.
"""

import logging
from collections import defaultdict

import orjson
from sqlalchemy import update
from tqdm import tqdm

from space_map_data.models.object import Object
from space_map_data.utils.db import get_session
from space_map_data.utils.paths import SOURCES_METADATA_DIR

logger = logging.getLogger(__name__)

WIKIDATA_OBJECTS_DIR = SOURCES_METADATA_DIR / "wikidata" / "objects"

# SQLite caps bind parameters per statement; chunk well below the ceiling.
_UPDATE_CHUNK = 500


def ingest() -> None:
    """Reset ``sitelinks_count`` then persist per-object counts from entity JSONs."""
    session = get_session()

    objects = (
        session.query(Object.id, Object.wikidata_qid)
        .filter(Object.wikidata_qid.is_not(None))
        .all()
    )

    qid_counts: dict[str, int] = {}
    missing_entities = 0
    ids_by_count: dict[int, list[str]] = defaultdict(list)
    for obj_id, qid in tqdm(objects, desc="Counting Wikidata sitelinks", unit="obj"):
        count = qid_counts.get(qid)
        if count is None:
            count = _count_sitelinks(qid)
            qid_counts[qid] = count
            if count == 0 and not (WIKIDATA_OBJECTS_DIR / f"{qid}.json").exists():
                missing_entities += 1
        if count:
            ids_by_count[count].append(obj_id)

    session.query(Object).update({Object.sitelinks_count: 0})
    for count, ids in ids_by_count.items():
        for start in range(0, len(ids), _UPDATE_CHUNK):
            chunk = ids[start : start + _UPDATE_CHUNK]
            session.execute(
                update(Object).where(Object.id.in_(chunk)).values(sitelinks_count=count)
            )
    session.commit()

    with_links = sum(len(ids) for ids in ids_by_count.values())
    logger.info(
        "sitelinks_count set for %d / %d QID-linked objects "
        "(%d QIDs had no entity JSON on disk)",
        with_links,
        len(objects),
        missing_entities,
    )


def _count_sitelinks(qid: str) -> int:
    """Sitelink count for ``qid``; 0 when the entity JSON is missing or corrupt."""
    path = WIKIDATA_OBJECTS_DIR / f"{qid}.json"
    if not path.exists():
        return 0
    try:
        entity = orjson.loads(path.read_bytes())
    except orjson.JSONDecodeError:
        logger.warning("Corrupt Wikidata JSON, skipping sitelinks: %s", path)
        return 0
    sitelinks = entity.get("sitelinks")
    return len(sitelinks) if isinstance(sitelinks, dict) else 0
