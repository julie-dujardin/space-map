"""Ingest CelesTrak gp-active.csv + group TLE files into the database."""

import csv
import logging
from pathlib import Path

from sqlalchemy import delete, insert, select, update
from tqdm import tqdm

from space_map_data.constants.earth_sats.satcat import SatcatObjectType
from space_map_data.constants.providers import ID_TYPES, PROVIDERS, make_object_id
from space_map_data.ingest.convert import (
    float_or_none,
    int_or_none,
    string_or_none,
)
from space_map_data.ingest.providers.objects.enrichment import (
    latest_day_dir,
    load_groups,
)
from space_map_data.models.object import (
    Object,
    ObjectType,
    CelesTrak as CelesTrakRow,
    ElementsScale,
    OrbitalSource,
    Satcat,
)
from space_map_data.utils.db import get_session

logger = logging.getLogger(__name__)


class CelesTrakIngestor:
    BATCH = 10_000

    def __init__(self, download_dir: Path):
        self.session = get_session()
        self.provider_dir = download_dir / PROVIDERS.CELESTRAK
        # The downloader writes daily snapshots under <year>/<month>/<day>/.
        # Ingest from the most-recent day so DB-side queries (object lists,
        # names, SGP4 extras) reflect the freshest element set; the export
        # reads every day's snapshot directly off disk for time-sliced
        # overlays so what's ingested here only matters outside the export.
        latest_day = latest_day_dir(self.provider_dir)
        self.csv_path = latest_day / "gp-active.csv"
        self.groups_dir = latest_day / "groups"
        self.total_rows = 0
        self.missing_satcat = 0
        # Pre-loaded from the satcat DB table (ingested earlier).
        self.satcat_object_types: dict[int, SatcatObjectType | None] = {}

    def _load_satcat_object_types(self) -> None:
        """Pre-load object_type from the satcat table for ObjectType classification."""
        rows = self.session.execute(
            select(Satcat.NORAD_CAT_ID, Satcat.object_type)
        ).all()
        self.satcat_object_types = {norad: otype for norad, otype in rows}
        logger.info(
            "Loaded %d SATCAT object types from DB", len(self.satcat_object_types)
        )

    def _parse_row(self, row: dict) -> dict:
        object_id = make_object_id(ID_TYPES.NORAD_SATCAT, row["NORAD_CAT_ID"])
        norad = int(row["NORAD_CAT_ID"])
        name = string_or_none(row["OBJECT_NAME"])
        if name == "UNKNOWN":
            name = None

        satcat_object_type = self.satcat_object_types.get(norad)
        if satcat_object_type is None:
            self.missing_satcat += 1
        object_type = (
            ObjectType.debris
            if satcat_object_type
            in (SatcatObjectType.ROCKET_BODY, SatcatObjectType.DEBRIS)
            else ObjectType.spacecraft
        )

        obj = dict(
            id=object_id,
            name=name,
            object_type=object_type,
            norad_cat_id=norad,
            cospar_id=string_or_none(row["OBJECT_ID"]),
            scale=ElementsScale.planet,
            parent_id="naif-399",
            orbital_source=OrbitalSource.celestrak,
            # Earth sats live in the daily TLE snapshots; rows with no
            # current TLE are dropped at overlay time, not here.
            has_position=True,
        )
        # Orbital elements proper (epoch, mean motion, eccentricity, etc.) are
        # not persisted: the export reads fresh values from the daily snapshot
        # files. Keep only metadata + SGP4 extras the writer reads at export
        # time (those get overwritten per-day too, but ingest seeds them so
        # consumers querying the DB outside export still see something).
        ct = dict(
            object_id=object_id,
            OBJECT_NAME=row["OBJECT_NAME"],
            TRAK_OBJECT_ID=row["OBJECT_ID"],
            EPHEMERIS_TYPE=int_or_none(row["EPHEMERIS_TYPE"]),
            CLASSIFICATION_TYPE=string_or_none(row["CLASSIFICATION_TYPE"]),
            NORAD_CAT_ID=norad,
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

    def _link_satcat(self, rows: list[dict]) -> None:
        """Set Satcat.object_id for satellites that now have Object rows."""
        for r in rows:
            norad = r["object"]["norad_cat_id"]
            object_id = r["object"]["id"]
            self.session.execute(
                update(Satcat)
                .where(Satcat.NORAD_CAT_ID == norad)
                .values(object_id=object_id)
            )
        self.session.commit()

    def _clear(self) -> None:
        self.session.execute(delete(CelesTrakRow))
        # Reset satcat object_id links for celestrak-sourced objects before
        # deleting those objects.
        self.session.execute(
            update(Satcat)
            .where(
                Satcat.object_id.in_(
                    select(Object.id).where(
                        Object.orbital_source == OrbitalSource.celestrak
                    )
                )
            )
            .values(object_id=None)
        )
        self.session.execute(
            delete(Object).where(Object.orbital_source == OrbitalSource.celestrak)
        )
        self.session.commit()

    def run(self) -> None:
        if not self.csv_path.exists():
            logger.warning("CelesTrak CSV not found at %s, skipping", self.csv_path)
            return
        self._clear()
        self._load_satcat_object_types()
        group_data = load_groups(self.groups_dir)

        total = _count_csv_rows(self.csv_path)

        batch: list[dict] = []
        seen_norad: set[int] = set()
        seen_cospar: set[str] = set()
        with open(self.csv_path, newline="") as f:
            for row in tqdm(csv.DictReader(f), total=total, desc="CelesTrak ingest"):
                seen_norad.add(int(row["NORAD_CAT_ID"]))
                cospar = string_or_none(row["OBJECT_ID"])
                if cospar is not None:
                    seen_cospar.add(cospar)
                batch.append(self._parse_row(row))
                self.total_rows += 1

                if len(batch) >= self.BATCH:
                    self._insert(batch)
                    self._link_satcat(batch)
                    batch = []
        self._insert(batch)
        self._link_satcat(batch)

        # Sats present only in group CSVs (e.g. debris not on the active list).
        batch = []
        group_only = 0
        for norad, row in tqdm(
            group_data.group_only_rows.items(),
            desc="CelesTrak group-only",
            unit="sat",
        ):
            if norad in seen_norad:
                continue
            cospar = string_or_none(row["OBJECT_ID"])
            if cospar is not None and cospar in seen_cospar:
                continue
            if cospar is not None:
                seen_cospar.add(cospar)
            batch.append(self._parse_row(row))
            self.total_rows += 1
            group_only += 1
            if len(batch) >= self.BATCH:
                self._insert(batch)
                self._link_satcat(batch)
                batch = []
        self._insert(batch)
        self._link_satcat(batch)

        logger.info(
            "Ingested %d CelesTrak satellites (%d from group CSVs only)",
            self.total_rows,
            group_only,
        )
        if self.missing_satcat:
            logger.info(
                "%d/%d satellites had no SATCAT match",
                self.missing_satcat,
                self.total_rows,
            )


def _count_csv_rows(path: Path) -> int:
    with open(path) as f:
        return sum(1 for _ in f) - 1


def ingest(download_dir: Path) -> None:
    CelesTrakIngestor(download_dir).run()
