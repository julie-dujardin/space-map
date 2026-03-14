"""Ingest Horizons bodies.csv into the database."""

import csv
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from space_map_data.models import Object, Frame, Horizons as HorizonsRow, OrbitalSource
from space_map_data.ingest.convert import float_or_none, int_or_none

logger = logging.getLogger(__name__)


def ingest(session: Session, download_dir: Path, *, limit: int | None = None) -> None:
    csv_path = download_dir / "horizons" / "bodies.csv"
    if not csv_path.exists():
        logger.warning("Horizons CSV not found at %s, skipping", csv_path)
        return

    count = 0
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            parent = int_or_none(row["parent_naif_id"])
            frame = Frame.heliocentric if parent == 0 else Frame.geocentric

            object = Object(
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
            object.horizons = HorizonsRow(
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
            session.add(object)
            count += 1
            if limit and count >= limit:
                break

    session.commit()
    logger.info("Ingested %d Horizons bodies", count)
