"""Ingest CelesTrak gp-active.csv into the database."""

import csv
import logging
from pathlib import Path

from space_map_data.constants.providers import ID_TYPES, PROVIDERS, make_object_id
from sqlalchemy import delete, insert
from tqdm import tqdm

from space_map_data.models.object import (
    Object,
    ObjectType,
    CelesTrak as CelesTrakRow,
    ElementsScale,
    OrbitalSource,
)
from space_map_data.ingest.convert import (
    mean_motion_to_a_km,
    float_or_none,
    int_or_none,
    string_or_none,
)
from space_map_data.utils.convert import date_to_julian
from space_map_data.utils.db import get_session

logger = logging.getLogger(__name__)


class CelesTrakIngestor:
    BATCH = 10_000

    def __init__(self, download_dir: Path):
        self.session = get_session()
        self.csv_path = download_dir / PROVIDERS.CELESTRAK / "gp-active.csv"
        self.total_rows = 0

    def _parse_row(self, row: dict) -> dict:
        mean_motion = float_or_none(row["MEAN_MOTION"])
        a_km = mean_motion_to_a_km(mean_motion) if mean_motion else None

        object_id = make_object_id(ID_TYPES.NORAD_SATCAT, row["NORAD_CAT_ID"])
        obj = dict(
            id=object_id,
            name=string_or_none(row["OBJECT_NAME"]),
            object_type=ObjectType.spacecraft,
            celestrak_norad_cat_id=int_or_none(row["NORAD_CAT_ID"]),
            celestrak_cospar_id=string_or_none(row["OBJECT_ID"]),
            epoch_jd=date_to_julian(row["EPOCH"]),
            a=a_km,
            e=float_or_none(row["ECCENTRICITY"]),
            i=float_or_none(row["INCLINATION"]),
            om=float_or_none(row["RA_OF_ASC_NODE"]),
            w=float_or_none(row["ARG_OF_PERICENTER"]),
            ma=float_or_none(row["MEAN_ANOMALY"]),
            n=mean_motion,
            scale=ElementsScale.planet,
            parent_naif_id=399,
            orbital_source=OrbitalSource.celestrak,
        )
        ct = dict(
            object_id=object_id,
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
            CLASSIFICATION_TYPE=string_or_none(row["CLASSIFICATION_TYPE"]),
            NORAD_CAT_ID=int_or_none(row["NORAD_CAT_ID"]),
            ELEMENT_SET_NO=int_or_none(row["ELEMENT_SET_NO"]),
            REV_AT_EPOCH=int_or_none(row["REV_AT_EPOCH"]),
            BSTAR=float_or_none(row["BSTAR"]),
            MEAN_MOTION_DOT=float_or_none(row["MEAN_MOTION_DOT"]),
            MEAN_MOTION_DDOT=float_or_none(row["MEAN_MOTION_DDOT"]),
        )
        return {"object": obj, "celestrak": ct}

    def _insert(self, rows: list[dict]) -> None:
        if not rows:
            return
        objects = [r["object"] for r in rows]
        self.session.execute(insert(Object), objects)
        ct_rows = [r["celestrak"] for r in rows]
        self.session.execute(insert(CelesTrakRow), ct_rows)
        self.session.commit()

    def _clear(self) -> None:
        self.session.execute(delete(CelesTrakRow))
        self.session.execute(
            delete(Object).where(Object.orbital_source == OrbitalSource.celestrak)
        )
        self.session.commit()

    def run(self) -> None:
        if not self.csv_path.exists():
            logger.warning("CelesTrak CSV not found at %s, skipping", self.csv_path)
            return
        self._clear()

        total = _count_csv_rows(self.csv_path)

        batch: list[dict] = []
        with open(self.csv_path, newline="") as f:
            for row in tqdm(csv.DictReader(f), total=total, desc="CelesTrak ingest"):
                batch.append(self._parse_row(row))
                self.total_rows += 1

                if len(batch) >= self.BATCH:
                    self._insert(batch)
                    batch = []

        self._insert(batch)
        logger.info("Ingested %d CelesTrak satellites", self.total_rows)


def _count_csv_rows(path: Path) -> int:
    with open(path) as f:
        return sum(1 for _ in f) - 1


def ingest(download_dir: Path) -> None:
    CelesTrakIngestor(download_dir).run()
