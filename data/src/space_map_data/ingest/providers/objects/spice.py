"""Ingest SPICE bodies.csv into the database."""

import csv
import logging
from pathlib import Path

from sqlalchemy import delete, insert, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from tqdm import tqdm

from space_map_data.constants.providers import ID_TYPES, PROVIDERS, make_object_id
from space_map_data.ingest.convert import float_or_none, int_or_none, string_or_none
from space_map_data.models.object import (
    Horizons as HorizonsRow,
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
        obj = {
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
            "parent_naif_id": int_or_none(row["parent_naif_id"]),
            "orbital_source": OrbitalSource.spice,
        }
        # Kepler elements + SPICE-fitted secular drift rates land on the
        # Horizons sub-table — SPICE-source rows join there for elements.
        # Horizons ingest just ran and either pre-populated this naif_id
        # from horizons/bodies.csv (we'll overwrite the element fields) or
        # didn't (we'll insert a fresh row).
        horizons_upsert = {
            "naif_id": naif_id,
            "object_id": object_pk,
            "JDTDB": float_or_none(row["JDTDB"]),
            "A": float_or_none(row["A"]),
            "EC": float_or_none(row["EC"]),
            "IN": float_or_none(row["IN"]),
            "OM": float_or_none(row["OM"]),
            "W": float_or_none(row["W"]),
            "MA": float_or_none(row["MA"]),
            "N": float_or_none(row["N"]),
            "om_dot": float_or_none(row.get("OM_DOT")),
            "w_dot": float_or_none(row.get("W_DOT")),
        }
        return {"object": obj, "horizons": horizons_upsert}

    def _insert(self, rows: list[dict]) -> None:
        if not rows:
            return
        self._takeover_sbdb_objects(rows)
        self.session.execute(insert(Object), [r["object"] for r in rows])
        # Upsert Horizons sub-table rows (overwrite kepler fields + drift
        # rates + object_id; preserve any pre-existing metadata not listed
        # in `set_`).
        for r in rows:
            stmt = sqlite_insert(HorizonsRow).values(**r["horizons"])
            stmt = stmt.on_conflict_do_update(
                index_elements=[HorizonsRow.naif_id],
                set_={k: stmt.excluded[k] for k in r["horizons"] if k != "naif_id"},
            )
            self.session.execute(stmt)
        self.session.commit()

    def _clear(self) -> None:
        # Reset SPICE-set fields on Horizons rows whose Object was spice-sourced
        # so a re-run without re-running Horizons doesn't leave stale values.
        spice_naif_ids = list(
            self.session.execute(
                select(Object.naif_id)
                .where(Object.orbital_source == OrbitalSource.spice)
                .where(Object.naif_id.is_not(None))
            ).scalars()
        )
        if spice_naif_ids:
            self.session.execute(
                update(HorizonsRow)
                .where(HorizonsRow.naif_id.in_(spice_naif_ids))
                .values(om_dot=None, w_dot=None)
            )
        self.session.execute(
            delete(Object).where(Object.orbital_source == OrbitalSource.spice)
        )
        self.session.commit()

    def _takeover_sbdb_objects(self, rows: list[dict]) -> None:
        """For rows that will claim an SBDB-sourced Object, re-point the SBDB
        physical-data row to the new SPICE Object ID, then delete the SBDB
        Object row. Preserves the physical data (diameter, rotation, etc.)."""
        takeovers = [
            (r["object"]["spkid"], r["object"]["id"])
            for r in rows
            if r["object"].get("spkid") is not None
        ]
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
