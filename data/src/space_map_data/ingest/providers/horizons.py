"""Ingest Horizons bodies.csv into the database."""

import csv
import logging
from pathlib import Path

from space_map_data.constants.providers import ID_TYPES
from sqlalchemy import insert, select
from tqdm import tqdm

from space_map_data.models.body import (
    Object,
    Frame,
    Horizons as HorizonsRow,
    ObjectType,
    OrbitalSource,
)
from space_map_data.ingest.convert import float_or_none, int_or_none, string_or_none
from space_map_data.utils.db import get_session

logger = logging.getLogger(__name__)


AUTHORITATIVE_ON = (
    ObjectType.barycenter,
    ObjectType.lagrange_point,
    ObjectType.star,
    ObjectType.planet,
    ObjectType.moon,
)


class HorizonsIngestor:
    BATCH = 10_000

    def __init__(self, download_dir: Path, *, limit: int | None = None):
        self.session = get_session()
        self.limit = limit
        self.csv_path = download_dir / "horizons" / "bodies.csv"
        self.total_rows = 0

    def get_spk_id(self, row: dict) -> int | None:
        """Return the SPK ID for a row, if it has one"""
        naif_id = int_or_none(row["naif_id"])
        if not naif_id:
            raise ValueError(f"Missing NAIF ID for: {row}")
        if naif_id == 999:
            # Pluto
            return 20134340
        if row["type"] in AUTHORITATIVE_ON:
            # Authoritative types won't have SPKIDs
            return None
        if 2_000_000 <= naif_id <= 2_999_999:
            # Asteroid in the 2m range => 20m range
            return naif_id + 18_000_000
        if 20_000_000 <= naif_id <= 29_999_999:
            # Asteroid in the 20m range => return as is
            return naif_id
        if 900_000_000 <= naif_id <= 999_999_999:
            # binary asteroid primaries
            return naif_id - 900_000_000
        if row["type"] == ObjectType.comet:
            # Comets: SPK ID and NAIF ID are the same
            return naif_id
        return None

    def get_cospar_id(self, row: dict) -> str | None:
        """Return the COSPAR ID for a row, if it has one"""
        if row["type"] == ObjectType.spacecraft:
            return string_or_none(row["designation"])
        return None

    def _parse_row(self, row: dict) -> dict:
        rows = {}
        spk_id = self.get_spk_id(row)
        cospar_id = self.get_cospar_id(row)
        if row["type"].strip() in AUTHORITATIVE_ON:
            object_pk = f"{ID_TYPES.NAIF}-{row['naif_id']}"
            rows["object"] = dict(
                id=object_pk,
                name=string_or_none(row["name"]) or string_or_none(row["designation"]),
                object_type=string_or_none(row["type"]),
                horizons_naif_id=int_or_none(row["naif_id"]),
                provisional_designation=string_or_none(row["designation"]),
                epoch_jd=float_or_none(row["JDTDB"]),
                a=float_or_none(row["A"]),
                e=float_or_none(row["EC"]),
                i=float_or_none(row["IN"]),
                om=float_or_none(row["OM"]),
                w=float_or_none(row["W"]),
                ma=float_or_none(row["MA"]),
                n=float_or_none(row["N"]),
                frame=Frame.heliocentric,
                parent_naif_id=int_or_none(row["parent_naif_id"]),
                orbital_source=OrbitalSource.horizons,
            )
        else:
            object_pk = spk_id
        rows["horizons"] = dict(
            object_id=object_pk,
            computed_spk_id=spk_id,
            cospar_id=cospar_id,
            name=string_or_none(row["name"]),
            naif_id=int_or_none(row["naif_id"]),
            type=string_or_none(row["type"]),
            center=string_or_none(row["center"]),
            parent_naif_id=int_or_none(row["parent_naif_id"]),
            designation=string_or_none(row["designation"]),
            extra=string_or_none(row["extra"]),
            JDTDB=float_or_none(row["JDTDB"]),
            calendar_date_tdb=string_or_none(row["Calendar Date (TDB)"]),
            EC=float_or_none(row["EC"]),
            QR=float_or_none(row["QR"]),
            IN_=float_or_none(row["IN"]),
            OM=float_or_none(row["OM"]),
            W=float_or_none(row["W"]),
            Tp=float_or_none(row["Tp"]),
            N=float_or_none(row["N"]),
            MA=float_or_none(row["MA"]),
            TA=float_or_none(row["TA"]),
            A=float_or_none(row["A"]),
            AD=float_or_none(row["AD"]),
            PR=float_or_none(row["PR"]),
        )
        return rows

    def _insert(self, rows: list[dict]) -> None:
        if not rows:
            return
        objects = [r["object"] for r in rows if "object" in r]
        hz_rows = [r["horizons"] for r in rows]
        self.session.execute(insert(Object), objects)
        self.session.execute(insert(HorizonsRow), hz_rows)
        self.session.commit()

    def match_spacecraft_to_bodies(self):
        """Match Horizons spacecraft rows to existing Objects (via NORAD/COSPAR),
        or create new Object entries for unmatched probes."""
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
                object_id = f"{ID_TYPES.NAIF}:{hz.naif_id}"
                new_objects.append(
                    Object(
                        id=object_id,
                        name=hz.name,
                        object_type=ObjectType.spacecraft,
                        horizons_naif_id=hz.naif_id,
                        celestrak_cospar_id=hz.cospar_id,
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

    def run(self) -> None:
        if not self.csv_path.exists():
            logger.warning("Horizons CSV not found at %s, skipping", self.csv_path)
            return

        total = _count_csv_rows(self.csv_path)
        if self.limit:
            total = min(total, self.limit)

        batch: list[dict] = []
        with open(self.csv_path, newline="") as f:
            for row in tqdm(csv.DictReader(f), total=total, desc="Horizons ingest"):
                batch.append(self._parse_row(row))
                self.total_rows += 1

                if len(batch) >= self.BATCH:
                    self._insert(batch)
                    batch = []

                if self.limit and self.total_rows >= self.limit:
                    break

        self._insert(batch)
        logger.info("Ingested %d Horizons bodies", self.total_rows)

        self.match_spacecraft_to_bodies()


def _count_csv_rows(path: Path) -> int:
    with open(path) as f:
        return sum(1 for _ in f) - 1


def ingest(download_dir: Path, *, limit: int | None = None) -> None:
    HorizonsIngestor(download_dir, limit=limit).run()
