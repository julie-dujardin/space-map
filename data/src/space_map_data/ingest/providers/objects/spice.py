"""Ingest SPICE bodies.csv into the database."""

import csv
import logging
from pathlib import Path

from sqlalchemy import delete, insert, select, update
from tqdm import tqdm

from space_map_data.constants.providers import ID_TYPES, PROVIDERS, make_object_id
from space_map_data.ingest.convert import float_or_none, int_or_none, string_or_none
from space_map_data.models.object import (
    ElementsScale,
    Object,
    ObjectType,
    OrbitalSource,
    SBDB,
)
from space_map_data.utils.db import get_session
from space_map_data.utils.naif import spk_id_from_naif

logger = logging.getLogger(__name__)

AUTHORITATIVE_ON = (
    ObjectType.barycenter,
    ObjectType.lagrange_point,
    ObjectType.star,
    ObjectType.planet,
    ObjectType.dwarf_planet,
    ObjectType.moon,
)


class SpiceIngestor:
    BATCH = 10_000

    def __init__(self, download_dir: Path):
        self.session = get_session()
        self.csv_path = download_dir / PROVIDERS.SPICE / "bodies.csv"
        self.total_rows = 0

    def _parse_row(self, row: dict[str, str]) -> dict | None:
        obj_type = string_or_none(row["type"])
        if obj_type not in AUTHORITATIVE_ON:
            return None

        naif_id = int_or_none(row["naif_id"])
        if naif_id is None:
            return None

        object_pk = make_object_id(ID_TYPES.NAIF, naif_id)
        # Link to SBDB physical data if this body has an SBDB counterpart
        spkid = spk_id_from_naif(naif_id, obj_type)
        return {
            "id": object_pk,
            "name": string_or_none(row["name"]),
            "provisional_designation": string_or_none(
                row.get("provisional_designation")
            ),
            "iau_roman_designation": string_or_none(row.get("iau_roman_designation")),
            "naif_id_extended": int_or_none(row.get("naif_id_extended")),
            "object_type": obj_type,
            "naif_id": naif_id,
            "spkid": spkid,
            "epoch_jd": float_or_none(row["JDTDB"]),
            "a": float_or_none(row["A"]),
            "e": float_or_none(row["EC"]),
            "i": float_or_none(row["IN"]),
            "om": float_or_none(row["OM"]),
            "w": float_or_none(row["W"]),
            "ma": float_or_none(row["MA"]),
            "n": float_or_none(row["N"]),
            "om_dot": float_or_none(row.get("OM_DOT")),
            "w_dot": float_or_none(row.get("W_DOT")),
            "scale": ElementsScale.system,
            "parent_naif_id": int_or_none(row["parent_naif_id"]),
            "orbital_source": OrbitalSource.spice,
        }

    def _insert(self, rows: list[dict]) -> None:
        if not rows:
            return
        self._takeover_sbdb_objects(rows)
        self.session.execute(insert(Object), rows)
        self.session.commit()

    def _clear(self) -> None:
        self.session.execute(
            delete(Object).where(Object.orbital_source == OrbitalSource.spice)
        )
        self.session.commit()

    def _takeover_sbdb_objects(self, rows: list[dict]) -> None:
        """For rows that will claim an SBDB-sourced Object, re-point the SBDB
        physical-data row to the new SPICE Object ID, then delete the SBDB
        Object row. Preserves the physical data (diameter, rotation, etc.)."""
        takeovers = [(r["spkid"], r["id"]) for r in rows if r.get("spkid") is not None]
        if not takeovers:
            return

        for spkid, new_object_id in takeovers:
            old_object_id = make_object_id(ID_TYPES.SPKID, spkid)
            # Does an SBDB-sourced Object exist with this spkid?
            existing = self.session.execute(
                select(Object.id).where(Object.id == old_object_id)
            ).scalar_one_or_none()
            if existing is None:
                continue
            # Re-point the SBDB physical-data row's FK, then delete the old Object
            self.session.execute(
                update(SBDB)
                .where(SBDB.object_id == old_object_id)
                .values(object_id=new_object_id)
            )
            self.session.execute(delete(Object).where(Object.id == old_object_id))
            logger.info(
                "SPICE took over SBDB object %s -> %s", old_object_id, new_object_id
            )
        self.session.commit()

    def run(self) -> None:
        if not self.csv_path.exists():
            logger.warning("SPICE CSV not found at %s, skipping", self.csv_path)
            return
        self._clear()

        total = _count_csv_rows(self.csv_path)

        batch: list[dict] = []
        with open(self.csv_path, newline="") as f:
            for row in tqdm(csv.DictReader(f), total=total, desc="SPICE ingest"):
                parsed = self._parse_row(row)
                if parsed is not None:
                    batch.append(parsed)
                self.total_rows += 1

                if len(batch) >= self.BATCH:
                    self._insert(batch)
                    batch = []

        self._insert(batch)
        logger.info("Ingested %d SPICE bodies", self.total_rows)


def _count_csv_rows(path: Path) -> int:
    with open(path) as f:
        return sum(1 for _ in f) - 1


def ingest(download_dir: Path) -> None:
    SpiceIngestor(download_dir).run()
