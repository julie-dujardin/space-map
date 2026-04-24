"""Populate ``Object.image_available`` from downloaded Commons metadata.

A Commons image is "available" when:

1. It appears in the Wikidata P18/P154 claims or Wikipedia pageimages of an
   Object's QID (or its SATCAT-linked operator QID — handled implicitly because
   the QID mapping lives on ``Object.wikidata_qid``), and
2. Its downloaded metadata file carries ``license_servable: true``.

The license decision is made once at download time (see
:func:`space_map_data.utils.commons_images.license_is_servable`) and just read
here — ingest never re-evaluates license rules.
"""

import logging

from sqlalchemy import update
from tqdm import tqdm

from space_map_data.models.object import Object
from space_map_data.utils.commons_images import (
    collect_qid_commons_filenames,
    is_servable_on_disk,
)
from space_map_data.utils.db import get_session

logger = logging.getLogger(__name__)

BATCH = 500


def ingest() -> None:
    """Set ``image_available`` on every Object based on downloaded image metadata.

    Clears the flag first so stale positives from earlier runs go away. Only
    objects with a ``wikidata_qid`` can have Commons images — the rest keep the
    default False.
    """
    session = get_session()
    session.query(Object).update({Object.image_available: False})
    session.commit()

    objects = (
        session.query(Object.id, Object.wikidata_qid)
        .filter(Object.wikidata_qid.is_not(None))
        .all()
    )

    # QIDs can repeat (shared pages e.g. for comet fragments), so cache the
    # filename lookup per QID — building it re-reads up to 7 JSON files.
    qid_cache: dict[str, list[str]] = {}
    servable_cache: dict[str, bool] = {}

    pending: list[str] = []
    count = 0
    for obj_id, qid in tqdm(objects, desc="Resolving image availability", unit="obj"):
        filenames = qid_cache.get(qid)
        if filenames is None:
            filenames = [e["filename"] for e in collect_qid_commons_filenames(qid)]
            qid_cache[qid] = filenames
        if not filenames:
            continue
        servable = False
        for name in filenames:
            cached = servable_cache.get(name)
            if cached is None:
                cached = is_servable_on_disk(name)
                servable_cache[name] = cached
            if cached:
                servable = True
                break
        if servable:
            pending.append(obj_id)
            if len(pending) >= BATCH:
                session.execute(
                    update(Object)
                    .where(Object.id.in_(pending))
                    .values(image_available=True)
                )
                count += len(pending)
                pending.clear()

    if pending:
        session.execute(
            update(Object).where(Object.id.in_(pending)).values(image_available=True)
        )
        count += len(pending)
    session.commit()
    logger.info(
        "image_available set on %d / %d QID-linked objects", count, len(objects)
    )
