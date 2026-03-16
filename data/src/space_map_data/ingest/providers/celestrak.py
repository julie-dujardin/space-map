"""Ingest CelesTrak gp-active.csv into the database."""

import csv
import logging
from pathlib import Path

from space_map_data.constants.providers import ID_TYPES
from sqlalchemy import insert
from tqdm import tqdm

from space_map_data.models.object import (
    Object,
    ObjectType,
    CelesTrak as CelesTrakRow,
    Frame,
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

    def __init__(self, download_dir: Path, *, limit: int | None = None):
        self.session = get_session()
        self.limit = limit
        self.csv_path = download_dir / "celes-trak" / "gp-active.csv"
        self.total_rows = 0

    def _parse_row(self, row: dict) -> dict:
        mean_motion = float_or_none(row["MEAN_MOTION"])
        a_km = mean_motion_to_a_km(mean_motion) if mean_motion else None

        obj = dict(
            id=f"{ID_TYPES.NORAD_SATCAT}-{row['NORAD_CAT_ID']}",
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
            frame=Frame.geocentric,
            parent_naif_id=399,
            orbital_source=OrbitalSource.celestrak,
        )
        ct = dict(
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
        ct_rows = [r["celestrak"] for r in rows]
        result = self.session.execute(insert(Object).returning(Object.id), objects)
        new_ids = [r[0] for r in result]
        for ct, obj_id in zip(ct_rows, new_ids):
            ct["object_id"] = obj_id
        self.session.execute(insert(CelesTrakRow), ct_rows)
        self.session.commit()

    def run(self) -> None:
        if not self.csv_path.exists():
            logger.warning("CelesTrak CSV not found at %s, skipping", self.csv_path)
            return

        total = _count_csv_rows(self.csv_path)
        if self.limit:
            total = min(total, self.limit)

        batch: list[dict] = []
        with open(self.csv_path, newline="") as f:
            for row in tqdm(csv.DictReader(f), total=total, desc="CelesTrak ingest"):
                batch.append(self._parse_row(row))
                self.total_rows += 1

                if len(batch) >= self.BATCH:
                    self._insert(batch)
                    batch = []

                if self.limit and self.total_rows >= self.limit:
                    break

        self._insert(batch)
        logger.info("Ingested %d CelesTrak satellites", self.total_rows)


def _count_csv_rows(path: Path) -> int:
    with open(path) as f:
        return sum(1 for _ in f) - 1


def ingest(download_dir: Path, *, limit: int | None = None) -> None:
    CelesTrakIngestor(download_dir, limit=limit).run()
