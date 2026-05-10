"""Set ``Object.has_wikipedia_description`` from downloaded Wikipedia summaries.

Walks ``DOWNLOAD_DIR/wikipedia/<lang>/<qid>.json`` for every Object with a
Wikidata QID; an Object is marked available when at least one language has a
non-empty summary (extract, description, or fullurl) and is not flagged
``missing``. Mirrors the reset-then-mark idempotency shape of
``image_available`` and ``map_texture_available``.
"""

import logging

import orjson
from sqlalchemy import update
from tqdm import tqdm

from space_map_data.constants.providers import LANGUAGES, PROVIDERS
from space_map_data.models.object import Object
from space_map_data.utils.db import get_session
from space_map_data.utils.paths import DOWNLOAD_DIR

logger = logging.getLogger(__name__)

WIKI_DIR = DOWNLOAD_DIR / PROVIDERS.WIKIPEDIA


def ingest() -> None:
    """Reset ``has_wikipedia_description`` then mark Objects with a usable summary."""
    session = get_session()

    objects = (
        session.query(Object.id, Object.wikidata_qid)
        .filter(Object.wikidata_qid.is_not(None))
        .all()
    )

    available_ids: set[str] = set()
    for obj_id, qid in tqdm(objects, desc="Checking Wikipedia summaries", unit="obj"):
        if _has_usable_summary(qid):
            available_ids.add(obj_id)

    session.query(Object).update({Object.has_wikipedia_description: False})
    if available_ids:
        session.execute(
            update(Object)
            .where(Object.id.in_(list(available_ids)))
            .values(has_wikipedia_description=True)
        )
    session.commit()

    logger.info(
        "has_wikipedia_description set for %d / %d QID-linked objects",
        len(available_ids),
        len(objects),
    )


def _has_usable_summary(qid: str) -> bool:
    """True if any language has a non-missing page with text or a URL."""
    for lang in LANGUAGES:
        path = WIKI_DIR / lang / f"{qid}.json"
        if not path.exists():
            continue
        try:
            page = orjson.loads(path.read_bytes())
        except orjson.JSONDecodeError:
            logger.warning("Corrupt Wikipedia JSON, skipping: %s", path)
            continue
        if page.get("missing"):
            continue
        if page.get("extract") or page.get("description") or page.get("fullurl"):
            return True
    return False
