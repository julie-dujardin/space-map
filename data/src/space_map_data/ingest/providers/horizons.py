"""Ingest Horizons bodies.csv into the database."""

import csv
import logging
from pathlib import Path

from sqlalchemy import insert
from sqlalchemy.orm import Session
from tqdm import tqdm

from space_map_data.models import Object, Frame, Horizons as HorizonsRow, OrbitalSource
from space_map_data.ingest.convert import float_or_none, int_or_none

logger = logging.getLogger(__name__)


class HorizonsIngestor:
    BATCH = 10_000

    def __init__(
        self, session: Session, download_dir: Path, *, limit: int | None = None
    ):
        self.session = session
        self.limit = limit
        self.csv_path = download_dir / "horizons" / "bodies.csv"
        self.total_rows = 0

    def _parse_row(self, row: dict) -> dict:
        parent = int_or_none(row["parent_naif_id"])
        frame = Frame.heliocentric if parent == 0 else Frame.geocentric

        obj = dict(
            name=row["name"].strip() or None,
            object_type=row["type"].strip(),
            horizons_naif_id=int_or_none(row["naif_id"]),
            epoch_jd=float_or_none(row["JDTDB"]),
            a=float_or_none(row["A"]),
            e=float_or_none(row["EC"]),
            i=float_or_none(row["IN"]),
            om=float_or_none(row["OM"]),
            w=float_or_none(row["W"]),
            ma=float_or_none(row["MA"]),
            n=float_or_none(row["N"]),
            frame=frame,
            parent_naif_id=parent,
            orbital_source=OrbitalSource.horizons,
        )
        hz = dict(
            name=row["name"],
            naif_id=int_or_none(row["naif_id"]),
            type=row["type"],
            center=row["center"],
            parent_naif_id=int_or_none(row["parent_naif_id"]),
            designation=row.get("designation", ""),
            extra=row.get("extra", ""),
            JDTDB=float_or_none(row["JDTDB"]),
            calendar_date_tdb=row.get("Calendar Date (TDB)", ""),
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
        return {"object": obj, "horizons": hz}

    def _insert(self, rows: list[dict]) -> None:
        if not rows:
            return
        objects = [r["object"] for r in rows]
        hz_rows = [r["horizons"] for r in rows]
        result = self.session.execute(insert(Object).returning(Object.id), objects)
        new_ids = [r[0] for r in result]
        for hz, obj_id in zip(hz_rows, new_ids):
            hz["object_id"] = obj_id
        self.session.execute(insert(HorizonsRow), hz_rows)
        self.session.commit()

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


def _count_csv_rows(path: Path) -> int:
    with open(path) as f:
        return sum(1 for _ in f) - 1


def ingest(session: Session, download_dir: Path, *, limit: int | None = None) -> None:
    HorizonsIngestor(session, download_dir, limit=limit).run()
