"""Set ``Object.discovery_year`` on the planets from their Wikidata P575.

Only Uranus and Neptune have one: the other planets were known in antiquity.
The year gates their rendering before it, as it does for the moons.
"""

import logging

import orjson
from sqlalchemy import update

from space_map_data.export.objects.wikidata_claims import discovery_year_from_claims
from space_map_data.ingest.providers.sitelinks import WIKIDATA_OBJECTS_DIR
from space_map_data.models.object import Object, ObjectType
from space_map_data.utils.db import get_session
from space_map_data.utils.mirror import local

logger = logging.getLogger(__name__)


def ingest() -> None:
    """Reset the planets' ``discovery_year``, then set it from P575."""
    session = get_session()
    planets = (
        session.query(Object.id, Object.wikidata_qid)
        .filter(Object.object_type == ObjectType.planet)
        .all()
    )
    years: dict[str, int] = {}
    for object_id, qid in planets:
        if qid is None:
            continue
        path = local(WIKIDATA_OBJECTS_DIR / f"{qid}.json")
        if not path.exists():
            logger.warning("No Wikidata entity for planet %s (%s)", object_id, qid)
            continue
        year = discovery_year_from_claims(orjson.loads(path.read_bytes())["claims"])
        if year is not None:
            years[object_id] = year

    session.execute(
        update(Object)
        .where(Object.object_type == ObjectType.planet)
        .values(discovery_year=None)
    )
    for object_id, year in years.items():
        session.execute(
            update(Object).where(Object.id == object_id).values(discovery_year=year)
        )
    session.commit()
    logger.info(
        "Planet discovery years: %s",
        ", ".join(f"{oid} {year}" for oid, year in sorted(years.items())) or "none",
    )
