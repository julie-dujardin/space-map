"""Ingest JPL's satellite physical parameters onto the moons SPICE created.

Each table row names its satellite by NAIF id, which joins on Object.naif_id.
A row that matches no Object is logged and skipped.
"""

import json
import logging
from pathlib import Path

from sqlalchemy import delete, insert, select

from space_map_data.models.object import JPLSatellitePhysical, Object
from space_map_data.utils.db import get_session

logger = logging.getLogger(__name__)

SATELLITES_FILE = Path("sources/position/jpl_satellite_physical/satellites.json")


def ingest(download_dir: Path) -> None:
    path = download_dir / SATELLITES_FILE
    if not path.exists():
        logger.warning("JPL satellite physical parameters not found at %s", path)
        return
    records = json.loads(path.read_text())
    session = get_session()
    with session.begin():
        naif_ids = [record["naif_id"] for record in records]
        by_naif = {
            naif_id: object_id
            for naif_id, object_id in session.execute(
                select(Object.naif_id, Object.id).where(Object.naif_id.in_(naif_ids))
            )
        }
        rows: list[dict] = []
        for record in records:
            object_id = by_naif.get(record["naif_id"])
            if object_id is None:
                logger.warning(
                    "JPL satellite %s (%d) matches no object, skipping",
                    record["name"],
                    record["naif_id"],
                )
                continue
            rows.append(
                {
                    "object_id": object_id,
                    "naif_id": record["naif_id"],
                    "gm_km3_s2": record["gm_km3_s2"],
                    "gm_sigma_km3_s2": record["gm_sigma_km3_s2"],
                    "gm_upper_limit": record["gm_upper_limit"],
                    "ephemeris": record["ephemeris"],
                }
            )
        session.execute(delete(JPLSatellitePhysical))
        if rows:
            session.execute(insert(JPLSatellitePhysical), rows)
    logger.info(
        "JPL satellite physical parameters: %d of %d rows", len(rows), len(records)
    )
