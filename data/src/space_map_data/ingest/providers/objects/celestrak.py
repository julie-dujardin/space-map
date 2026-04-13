"""Ingest CelesTrak gp-active.csv + satcat.csv + group files into the database."""

import csv
import logging
from pathlib import Path

from space_map_data.constants.constellations import (
    CONSTELLATIONS,
    GROUP_TO_SLUG,
    slug_from_name,
)
from space_map_data.constants.providers import ID_TYPES, PROVIDERS, make_object_id
from sqlalchemy import delete, insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from tqdm import tqdm

from space_map_data.models.object import (
    Object,
    ObjectType,
    CelesTrak as CelesTrakRow,
    Constellation,
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
        self.provider_dir = download_dir / PROVIDERS.CELESTRAK
        self.csv_path = self.provider_dir / "gp-active.csv"
        self.satcat_path = self.provider_dir / "satcat.csv"
        self.groups_dir = self.provider_dir / "groups"
        self.total_rows = 0
        self.missing_satcat = 0
        self.satcat: dict[int, dict[str, str]] = {}
        self.group_constellation: dict[int, str] = {}

    def _load_satcat(self) -> None:
        if not self.satcat_path.exists():
            logger.warning(
                "SATCAT not found at %s; skipping enrichment", self.satcat_path
            )
            return
        with open(self.satcat_path, newline="") as f:
            for row in csv.DictReader(f):
                norad = int_or_none(row.get("NORAD_CAT_ID"))
                if norad is None:
                    continue
                self.satcat[norad] = row
        logger.info("Loaded %d SATCAT rows", len(self.satcat))

    def _load_groups(self) -> None:
        if not self.groups_dir.exists():
            logger.warning(
                "Groups dir not found at %s; skipping constellation-group tagging",
                self.groups_dir,
            )
            return
        for group_file in sorted(self.groups_dir.glob("*.csv")):
            slug = GROUP_TO_SLUG.get(group_file.stem)
            if slug is None:
                logger.warning(
                    "Group file %s has no mapped constellation; skipping",
                    group_file.name,
                )
                continue
            if group_file.stat().st_size == 0:
                logger.info("Group file %s is empty", group_file.name)
                continue
            count = 0
            with open(group_file, newline="") as f:
                for row in csv.DictReader(f):
                    norad = int_or_none(row.get("NORAD_CAT_ID"))
                    if norad is None:
                        continue
                    self.group_constellation[norad] = slug
                    count += 1
            logger.info("Group %s -> %d sats", slug, count)

    def _upsert_constellations(self) -> None:
        rows = [
            {"slug": c.slug, "name": c.name, "wikidata_qid": c.wikidata_qid}
            for c in CONSTELLATIONS
        ]
        stmt = sqlite_insert(Constellation).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["slug"],
            set_={
                "name": stmt.excluded.name,
                "wikidata_qid": stmt.excluded.wikidata_qid,
            },
        )
        self.session.execute(stmt)
        self.session.commit()

    def _constellation_for(self, norad: int, name: str | None) -> str | None:
        slug = slug_from_name(name)
        if slug is not None:
            return slug
        return self.group_constellation.get(norad)

    def _parse_row(self, row: dict) -> dict:
        mean_motion = float_or_none(row["MEAN_MOTION"])
        a_km = mean_motion_to_a_km(mean_motion) if mean_motion else None

        object_id = make_object_id(ID_TYPES.NORAD_SATCAT, row["NORAD_CAT_ID"])
        norad = int(row["NORAD_CAT_ID"])
        name = string_or_none(row["OBJECT_NAME"])
        sat = self.satcat.get(norad)
        if sat is None:
            self.missing_satcat += 1
        constellation = self._constellation_for(norad, name)

        obj = dict(
            id=object_id,
            name=name,
            object_type=ObjectType.spacecraft,
            celestrak_norad_cat_id=norad,
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
            NORAD_CAT_ID=norad,
            ELEMENT_SET_NO=int_or_none(row["ELEMENT_SET_NO"]),
            REV_AT_EPOCH=int_or_none(row["REV_AT_EPOCH"]),
            BSTAR=float_or_none(row["BSTAR"]),
            MEAN_MOTION_DOT=float_or_none(row["MEAN_MOTION_DOT"]),
            MEAN_MOTION_DDOT=float_or_none(row["MEAN_MOTION_DDOT"]),
            OBJECT_TYPE=string_or_none(sat["OBJECT_TYPE"]) if sat else None,
            OPS_STATUS_CODE=string_or_none(sat["OPS_STATUS_CODE"]) if sat else None,
            OWNER=string_or_none(sat["OWNER"]) if sat else None,
            LAUNCH_DATE=string_or_none(sat["LAUNCH_DATE"]) if sat else None,
            LAUNCH_SITE=string_or_none(sat["LAUNCH_SITE"]) if sat else None,
            DECAY_DATE=string_or_none(sat["DECAY_DATE"]) if sat else None,
            PERIOD=float_or_none(sat["PERIOD"]) if sat else None,
            APOGEE=float_or_none(sat["APOGEE"]) if sat else None,
            PERIGEE=float_or_none(sat["PERIGEE"]) if sat else None,
            RCS=float_or_none(sat["RCS"]) if sat else None,
            DATA_STATUS_CODE=string_or_none(sat["DATA_STATUS_CODE"]) if sat else None,
            ORBIT_CENTER=string_or_none(sat["ORBIT_CENTER"]) if sat else None,
            ORBIT_TYPE=string_or_none(sat["ORBIT_TYPE"]) if sat else None,
            constellation_slug=constellation,
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
        self._upsert_constellations()
        self._load_satcat()
        self._load_groups()

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
        if self.missing_satcat:
            logger.info(
                "%d/%d gp-active rows had no SATCAT match",
                self.missing_satcat,
                self.total_rows,
            )


def _count_csv_rows(path: Path) -> int:
    with open(path) as f:
        return sum(1 for _ in f) - 1


def ingest(download_dir: Path) -> None:
    CelesTrakIngestor(download_dir).run()
