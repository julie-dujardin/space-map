"""Ingest CelesTrak gp-active.csv into the database."""

import csv
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from space_map_data.models import (
    Object,
    ObjectType,
    CelesTrak as CelesTrakRow,
    Frame,
    OrbitalSource,
)
from space_map_data.ingest.convert import (
    iso_to_jd,
    mean_motion_to_a_km,
    float_or_none,
    int_or_none,
)

logger = logging.getLogger(__name__)


def ingest(session: Session, download_dir: Path, *, limit: int | None = None) -> None:
    csv_path = download_dir / "celes-trak" / "gp-active.csv"
    if not csv_path.exists():
        logger.warning("CelesTrak CSV not found at %s, skipping", csv_path)
        return

    count = 0
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            mean_motion = float_or_none(row["MEAN_MOTION"])
            a_km = mean_motion_to_a_km(mean_motion) if mean_motion else None

            object = Object(
                name=row["OBJECT_NAME"].strip(),
                object_type=ObjectType.satellite,
                celestrak_norad_cat_id=int_or_none(row["NORAD_CAT_ID"]),
                epoch_jd=iso_to_jd(row["EPOCH"]),
                a=a_km,
                e=float_or_none(row["ECCENTRICITY"]),
                i=float_or_none(row["INCLINATION"]),
                om=float_or_none(row["RA_OF_ASC_NODE"]),
                w=float_or_none(row["ARG_OF_PERICENTER"]),
                ma=float_or_none(row["MEAN_ANOMALY"]),
                n=mean_motion,
                frame=Frame.geocentric,
                parent_naif_id=399,
                orbital_source=OrbitalSource.celestrak,
            )
            object.celestrak = CelesTrakRow(
                OBJECT_NAME=row["OBJECT_NAME"],
                TRAK_OBJECT_ID=row["OBJECT_ID"],
                EPOCH=row["EPOCH"],
                MEAN_MOTION=mean_motion,
                ECCENTRICITY=float_or_none(row["ECCENTRICITY"]),
                INCLINATION=float_or_none(row["INCLINATION"]),
                RA_OF_ASC_NODE=float_or_none(row["RA_OF_ASC_NODE"]),
                ARG_OF_PERICENTER=float_or_none(row["ARG_OF_PERICENTER"]),
                MEAN_ANOMALY=float_or_none(row["MEAN_ANOMALY"]),
                EPHEMERIS_TYPE=int_or_none(row["EPHEMERIS_TYPE"]),
                CLASSIFICATION_TYPE=row.get("CLASSIFICATION_TYPE", ""),
                NORAD_CAT_ID=int_or_none(row["NORAD_CAT_ID"]),
                ELEMENT_SET_NO=int_or_none(row["ELEMENT_SET_NO"]),
                REV_AT_EPOCH=int_or_none(row["REV_AT_EPOCH"]),
                BSTAR=float_or_none(row["BSTAR"]),
                MEAN_MOTION_DOT=float_or_none(row["MEAN_MOTION_DOT"]),
                MEAN_MOTION_DDOT=float_or_none(row["MEAN_MOTION_DDOT"]),
            )
            session.add(object)
            count += 1
            if limit and count >= limit:
                break

    session.commit()
    logger.info("Ingested %d CelesTrak satellites", count)
