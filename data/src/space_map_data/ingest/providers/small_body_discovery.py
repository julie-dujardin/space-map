"""Set ``Object.discovery_date`` on the SBDB bodies from their Wikidata P575."""

import logging

import orjson
from sqlalchemy import update

from space_map_data.export.objects.wikidata_claims import discovery_date_from_claims
from space_map_data.ingest.providers.sitelinks import WIKIDATA_OBJECTS_DIR
from space_map_data.models.object import Object
from space_map_data.utils.db import get_session
from space_map_data.utils.mirror import local

logger = logging.getLogger(__name__)


def ingest() -> None:
    """Reset every ``discovery_date``, then set it from P575 on SBDB bodies."""
    session = get_session()
    bodies = (
        session.query(Object.id, Object.wikidata_qid)
        .filter(Object.spkid.is_not(None), Object.wikidata_qid.is_not(None))
        .all()
    )
    dates: list[dict] = []
    missing = 0
    for object_id, qid in bodies:
        path = local(WIKIDATA_OBJECTS_DIR / f"{qid}.json")
        if not path.exists():
            missing += 1
            continue
        claims = orjson.loads(path.read_bytes())["claims"]
        if (date := discovery_date_from_claims(claims)) is not None:
            dates.append({"id": object_id, "discovery_date": date})

    session.execute(update(Object).values(discovery_date=None))
    if dates:
        session.execute(update(Object), dates)
    session.commit()
    logger.info(
        "Small-body discovery dates: %d of %d bodies with a QID (%d without an entity)",
        len(dates),
        len(bodies),
        missing,
    )
