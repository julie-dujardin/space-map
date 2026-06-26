"""Ingest GCAT lv.tsv into the launch_vehicle table.

GCAT lists one row per (LV_Name, LV_Variant); launchlog carries only the bare
LV_Name, so we collapse to a single row per name — preferring the base variant
("-") and otherwise the first seen, since physical specs are shared across the
sub-variants of a name. The table feeds launch-vehicle group pages: `family`
buckets names into a lineage and the spec columns populate page facts.
"""

import csv
import logging
from pathlib import Path

from sqlalchemy import delete, insert

from space_map_data.models.object import LaunchVehicle
from space_map_data.utils.db import get_session

logger = logging.getLogger(__name__)

# lv.tsv column order (header line is "#LV_Name\t...").
COLUMNS = (
    "lv_name",
    "family",
    "manufacturer",
    "variant",
    "alias",
    "min_stage",
    "max_stage",
    "length_m",
    "lflag",
    "diameter_m",
    "dflag",
    "launch_mass_t",
    "mflag",
    "leo_capacity_kg",
    "gto_capacity_kg",
    "thrust_kn",
    "lv_class",
    "apogee",
    "range",
)
_FLOAT_FIELDS = (
    "length_m",
    "diameter_m",
    "launch_mass_t",
    "leo_capacity_kg",
    "gto_capacity_kg",
    "thrust_kn",
)
_INT_FIELDS = ("min_stage", "max_stage")
_KEEP = (
    "lv_name",
    "family",
    "manufacturer",
    "alias",
    "lv_class",
    *_INT_FIELDS,
    *_FLOAT_FIELDS,
)


def _clean(val: str | None) -> str | None:
    """Strip whitespace; treat empty and the bare "-" sentinel as None."""
    if val is None:
        return None
    val = val.strip()
    if not val or val == "-":
        return None
    return val


class LaunchVehicleIngestor:
    BATCH = 5_000

    def __init__(self, download_dir: Path):
        self.session = get_session()
        self.path = download_dir / "sources" / "position" / "gcat" / "lv.tsv"
        self.malformed = 0
        self.unparsed_numbers = 0

    def _parse_rows(self) -> list[dict]:
        # name → row; "-" base variant wins, else first seen.
        by_name: dict[str, dict] = {}
        collapsed = 0
        with open(self.path, newline="") as f:
            for raw in csv.reader(f, delimiter="\t"):
                if not raw or raw[0].startswith("#"):
                    continue
                if len(raw) != len(COLUMNS):
                    self.malformed += 1
                    continue
                fields = {col: _clean(val) for col, val in zip(COLUMNS, raw)}
                name = fields["lv_name"]
                if name is None:
                    continue
                is_base = fields["variant"] is None
                if name in by_name:
                    collapsed += 1
                    if not is_base:
                        continue  # keep the existing (possibly base) row
                row: dict[str, object] = {k: fields[k] for k in _KEEP}
                for k in _INT_FIELDS:
                    row[k] = self._to_int(fields[k])
                for k in _FLOAT_FIELDS:
                    row[k] = self._to_float(fields[k])
                by_name[name] = row
        if collapsed:
            logger.info(
                "Collapsed %d lv.tsv sub-variant rows into name rows", collapsed
            )
        if self.malformed:
            logger.warning("Skipped %d malformed lv.tsv rows", self.malformed)
        return list(by_name.values())

    def _to_int(self, val: str | None) -> int | None:
        if val is None:
            return None
        try:
            return int(val)
        except ValueError:
            self.unparsed_numbers += 1
            return None

    def _to_float(self, val: str | None) -> float | None:
        if val is None:
            return None
        try:
            return float(val)
        except ValueError:
            self.unparsed_numbers += 1
            return None

    def _insert(self, rows: list[dict]) -> None:
        for i in range(0, len(rows), self.BATCH):
            self.session.execute(insert(LaunchVehicle), rows[i : i + self.BATCH])
        self.session.commit()

    def run(self) -> None:
        if not self.path.exists():
            logger.warning("lv.tsv not found at %s, skipping", self.path)
            return
        self.session.execute(delete(LaunchVehicle))
        self.session.commit()
        rows = self._parse_rows()
        self._insert(rows)
        logger.info("Ingested %d launch-vehicle rows", len(rows))
        if self.unparsed_numbers:
            logger.warning(
                "%d lv.tsv numeric fields could not be parsed", self.unparsed_numbers
            )


def ingest(download_dir: Path) -> None:
    LaunchVehicleIngestor(download_dir).run()
