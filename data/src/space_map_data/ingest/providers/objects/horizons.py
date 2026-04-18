"""Ingest Horizons bodies.csv — spacecraft only.

Planets, moons, barycenters come from SPICE; asteroids/comets from SBDB.
Horizons' remaining role is spacecraft discovery and NAIF ID cross-referencing.
"""

import csv
import logging
from pathlib import Path

from space_map_data.constants.providers import ID_TYPES, PROVIDERS, make_object_id
from sqlalchemy import delete, insert, select, update
from tqdm import tqdm

from space_map_data.models.object import (
    Object,
    ElementsScale,
    Horizons as HorizonsRow,
    ObjectType,
    OrbitalSource,
    Satcat,
)
from space_map_data.ingest.convert import float_or_none, int_or_none, string_or_none
from space_map_data.utils.db import get_session

logger = logging.getLogger(__name__)


class HorizonsIngestor:
    BATCH = 10_000

    def __init__(self, download_dir: Path):
        self.session = get_session()
        self.csv_path = download_dir / PROVIDERS.HORIZONS / "bodies.csv"
        self.total_rows = 0

    def _parse_row(self, row: dict) -> dict | None:
        """Parse a Horizons CSV row into a HorizonsRow dict.

        Only spacecraft rows are used for Object creation (via
        match_spacecraft_to_bodies). All rows are stored in the Horizons
        mirror table for NAIF ID cross-referencing.
        """
        naif_id = int_or_none(row["naif_id"])
        if naif_id is None:
            return None

        obj_type = string_or_none(row["type"])
        cospar_id = (
            string_or_none(row["designation"])
            if obj_type == ObjectType.spacecraft
            else None
        )

        return {
            "cospar_id": cospar_id,
            "name": string_or_none(row["name"]),
            "naif_id": naif_id,
            "type": obj_type,
            "center": string_or_none(row.get("center")),
            "parent_naif_id": int_or_none(row["parent_naif_id"]),
            "designation": string_or_none(row["designation"]),
            "extra": string_or_none(row.get("extra")),
            "JDTDB": float_or_none(row["JDTDB"]),
            "calendar_date_tdb": string_or_none(row.get("Calendar Date (TDB)")),
            "EC": float_or_none(row["EC"]),
            "QR": float_or_none(row["QR"]),
            "IN_": float_or_none(row["IN"]),
            "OM": float_or_none(row["OM"]),
            "W": float_or_none(row["W"]),
            "Tp": float_or_none(row["Tp"]),
            "N": float_or_none(row["N"]),
            "MA": float_or_none(row["MA"]),
            "TA": float_or_none(row["TA"]),
            "A": float_or_none(row["A"]),
            "AD": float_or_none(row["AD"]),
            "PR": float_or_none(row["PR"]),
        }

    def _insert(self, rows: list[dict]) -> None:
        if not rows:
            return
        self.session.execute(insert(HorizonsRow), rows)
        self.session.commit()

    def match_spacecraft_to_bodies(self) -> None:
        """Match Horizons spacecraft rows to existing Objects (via NORAD/COSPAR),
        or create new Object entries for unmatched probes.
        """
        spacecraft = self.session.execute(
            select(HorizonsRow, Object)
            .outerjoin(Object, Object.celestrak_cospar_id == HorizonsRow.cospar_id)
            .where(HorizonsRow.type == ObjectType.spacecraft)
        ).all()

        new_objects = []
        for hz, obj in spacecraft:
            if obj is not None:
                # Existing object found via COSPAR — point horizons row at it
                hz.object_id = obj.id
            else:
                # No match — create a new Object for this probe
                object_id = make_object_id(ID_TYPES.NAIF, hz.naif_id)
                new_objects.append(
                    Object(
                        id=object_id,
                        name=hz.name,
                        object_type=ObjectType.spacecraft,
                        horizons_naif_id=hz.naif_id,
                        celestrak_cospar_id=hz.cospar_id,
                        epoch_jd=hz.JDTDB,
                        a=hz.A,
                        e=hz.EC,
                        i=hz.IN_,
                        om=hz.OM,
                        w=hz.W,
                        ma=hz.MA,
                        n=hz.N,
                        scale=ElementsScale.system,
                        parent_naif_id=hz.parent_naif_id,
                        orbital_source=OrbitalSource.horizons,
                    )
                )
                hz.object_id = object_id

        self.session.add_all(new_objects)
        self.session.commit()
        logger.info(
            "Matched %d spacecraft: %d existing, %d new",
            len(spacecraft),
            len(spacecraft) - len(new_objects),
            len(new_objects),
        )

    def _link_satcat(self) -> None:
        """Link SATCAT rows to spacecraft Objects via COSPAR ID.

        CelesTrak links SATCAT rows for active satellites it creates Objects
        for. This catches the remaining cases: deep-space probes and other
        spacecraft that Horizons created or matched Objects for.
        """
        obj_subq = (
            select(Object.id)
            .where(Object.celestrak_cospar_id == Satcat.COSPAR_ID)
            .where(Object.horizons_naif_id.isnot(None))
            .correlate(Satcat)
        )
        result = self.session.execute(
            update(Satcat)
            .where(Satcat.object_id.is_(None))
            .where(obj_subq.exists())
            .values(object_id=obj_subq.scalar_subquery())
        )
        self.session.commit()
        if result.rowcount:
            logger.info(
                "Linked %d SATCAT rows to Horizons spacecraft via COSPAR",
                result.rowcount,
            )

    def insert_missing_data(self) -> None:
        """Cross-reference Horizons NAIF IDs into CelesTrak objects via COSPAR."""
        self.session.execute(
            update(Object)
            .where(Object.horizons_naif_id.is_(None))
            .where(
                select(HorizonsRow.naif_id)
                .where(HorizonsRow.cospar_id == Object.celestrak_cospar_id)
                .correlate(Object)
                .exists()
            )
            .values(
                horizons_naif_id=select(HorizonsRow.naif_id)
                .where(HorizonsRow.cospar_id == Object.celestrak_cospar_id)
                .correlate(Object)
                .scalar_subquery()
            )
        )

        self.session.commit()

    def _clear(self) -> None:
        self.session.execute(delete(HorizonsRow))
        self.session.execute(
            delete(Object).where(Object.orbital_source == OrbitalSource.horizons)
        )
        # Only clear horizons_naif_id on rows that Horizons set (via cross-referencing).
        # SPICE-owned rows keep their authoritative NAIF IDs.
        self.session.execute(
            update(Object)
            .where(Object.orbital_source != OrbitalSource.spice)
            .values(horizons_naif_id=None)
        )
        self.session.commit()

    def run(self) -> None:
        if not self.csv_path.exists():
            logger.warning("Horizons CSV not found at %s, skipping", self.csv_path)
            return
        self._clear()

        total = _count_csv_rows(self.csv_path)

        batch: list[dict] = []
        with open(self.csv_path, newline="") as f:
            for row in tqdm(csv.DictReader(f), total=total, desc="Horizons ingest"):
                parsed = self._parse_row(row)
                if parsed is not None:
                    batch.append(parsed)
                self.total_rows += 1

                if len(batch) >= self.BATCH:
                    self._insert(batch)
                    batch = []

        self._insert(batch)
        logger.info("Ingested %d Horizons rows", self.total_rows)

        self.match_spacecraft_to_bodies()
        self.insert_missing_data()
        self._link_satcat()


def _count_csv_rows(path: Path) -> int:
    with open(path) as f:
        return sum(1 for _ in f) - 1


def ingest(download_dir: Path) -> None:
    HorizonsIngestor(download_dir).run()
