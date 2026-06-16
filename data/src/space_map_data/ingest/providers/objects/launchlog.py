"""Ingest GCAT launchlog.tsv into the launchlog table, then link to objects.

Runs after the earth-sat chain (satcat → probes → celestrak) so every Object
that can carry a COSPAR already exists. Each launchlog row is matched to an
Object by `piece` == `Object.cospar_id`; the match sets `Object.launchlog_jcat`.
"""

import csv
import logging
from pathlib import Path

from sqlalchemy import delete, insert, select, update

from space_map_data.constants.earth_sats.launchlog import parse_sat_type
from space_map_data.ingest.convert import gcat_date_to_iso
from space_map_data.models.object import Launchlog, Object
from space_map_data.utils.db import get_session

logger = logging.getLogger(__name__)

# launchlog.tsv column order (header line is "#Launch_Tag\t...").
COLUMNS = (
    "launch_tag",
    "launch_date",
    "piece",
    "type",
    "name",
    "plname",
    "jcat",
    "sat_owner",
    "sat_state",
    "lv_type",
    "flight_id",
    "platform",
    "launch_site",
    "launch_pad",
    "ascent_site",
    "ascent_pad",
    "agency",
    "lv_state",
    "launch_code",
    "ltcite",
)


def _clean(val: str | None) -> str | None:
    """Strip whitespace; treat empty and the bare "-" sentinel as None."""
    if val is None:
        return None
    val = val.strip()
    if not val or val == "-":
        return None
    return val


class LaunchlogIngestor:
    BATCH = 10_000

    def __init__(self, download_dir: Path):
        self.session = get_session()
        self.path = download_dir / "sources" / "position" / "gcat" / "launchlog.tsv"
        self.total_rows = 0
        self.unparsed_dates = 0
        self.multi_piece = 0
        # piece (COSPAR) → primary JCAT, used to set Object.launchlog_jcat.
        self.primary_by_piece: dict[str, str] = {}

    def _parse_rows(self) -> list[dict]:
        """Parse launchlog rows and build the piece → primary-JCAT link map.

        A piece is not unique (sub-objects share it); pick the lexicographically
        smallest JCAT as the primary — launch-level fields (vehicle, pad, site,
        flight) are identical across pieces of the same launch anyway.
        """
        rows: list[dict] = []
        seen_jcat: set[str] = set()
        with open(self.path, newline="") as f:
            reader = csv.reader(f, delimiter="\t")
            for raw in reader:
                # Skip the two comment lines (header + "# Updated ...").
                if not raw or raw[0].startswith("#"):
                    continue
                if len(raw) != len(COLUMNS):
                    logger.warning("Skipping malformed launchlog row: %r", raw[:3])
                    continue
                fields = {col: _clean(val) for col, val in zip(COLUMNS, raw)}
                jcat = fields["jcat"]
                if jcat is None:
                    continue
                if jcat in seen_jcat:
                    logger.warning("Duplicate launchlog JCAT %s — keeping first", jcat)
                    continue
                seen_jcat.add(jcat)

                raw_date = fields.pop("launch_date")  # not a column; kept iso + flag
                launch_date_iso = gcat_date_to_iso(raw_date)
                if launch_date_iso is None and raw_date is not None:
                    self.unparsed_dates += 1

                piece = fields["piece"]
                if piece is not None:
                    existing = self.primary_by_piece.get(piece)
                    if existing is None:
                        self.primary_by_piece[piece] = jcat
                    else:
                        self.multi_piece += 1
                        if jcat < existing:
                            self.primary_by_piece[piece] = jcat

                raw_type = fields.pop("type")  # decoded into byte-2..9 columns
                row: dict[str, object] = dict(fields)
                row["launch_date_iso"] = launch_date_iso
                row["launch_date_uncertain"] = raw_date is not None and "?" in raw_date
                row.update(parse_sat_type(raw_type))
                rows.append(row)
        return rows

    def _insert(self, rows: list[dict]) -> None:
        for i in range(0, len(rows), self.BATCH):
            self.session.execute(insert(Launchlog), rows[i : i + self.BATCH])
        self.session.commit()

    def _link_objects(self) -> None:
        """Set Object.launchlog_jcat by matching launchlog.piece to cospar_id."""
        object_rows = self.session.execute(
            select(Object.id, Object.cospar_id).where(Object.cospar_id.is_not(None))
        ).all()
        updates = [
            {"id": oid, "launchlog_jcat": self.primary_by_piece[cospar]}
            for oid, cospar in object_rows
            if cospar in self.primary_by_piece
        ]
        for i in range(0, len(updates), self.BATCH):
            self.session.execute(update(Object), updates[i : i + self.BATCH])
        self.session.commit()

        logger.info(
            "Linked %d objects to launchlog rows (%d pieces shared by >1 JCAT)",
            len(updates),
            self.multi_piece,
        )

    def _clear(self) -> None:
        self.session.execute(
            update(Object)
            .where(Object.launchlog_jcat.is_not(None))
            .values(launchlog_jcat=None)
        )
        self.session.execute(delete(Launchlog))
        self.session.commit()

    def run(self) -> None:
        if not self.path.exists():
            logger.warning("launchlog.tsv not found at %s, skipping", self.path)
            return
        self._clear()
        rows = self._parse_rows()
        self.total_rows = len(rows)
        self._insert(rows)
        self._link_objects()
        logger.info("Ingested %d launchlog rows", self.total_rows)
        if self.unparsed_dates:
            logger.warning(
                "%d/%d launch dates could not be parsed to a datetime",
                self.unparsed_dates,
                self.total_rows,
            )


def ingest(download_dir: Path) -> None:
    LaunchlogIngestor(download_dir).run()
