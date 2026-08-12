"""Ingest GCAT sites.tsv and lp.tsv into the launch_site / launch_pad tables.

Rows with no coordinate are kept rather than dropped: a launchlog row can name
a site GCAT knows only as a code (mobile sea platforms, airspace release
boxes), and keeping the row preserves the name even where there is no point to
put on a globe. Consumers filter on `latitude is not None`.
"""

import csv
import logging
from pathlib import Path

from sqlalchemy import delete, insert

from space_map_data.models.object import LaunchPad, LaunchSite
from space_map_data.utils.db import get_session

logger = logging.getLogger(__name__)

# sites.tsv column order (header line is "#Site\t...").
SITE_COLUMNS = (
    "code",
    "_code_compat",  # blank, kept by GCAT for back compatibility
    "ucode",
    "site_type",
    "state_code",
    "t_start",
    "t_stop",
    "short_name",
    "name",
    "location",
    "longitude",
    "latitude",
    "error_deg",
    "parent",
    "short_ename",
    "ename",
    "site_group",
    "uname",
)
# lp.tsv repeats the site layout minus the Group column.
PAD_COLUMNS = (
    "site",
    "code",
    "ucode",
    "pad_type",
    "state_code",
    "t_start",
    "t_stop",
    "short_name",
    "name",
    "location",
    "longitude",
    "latitude",
    "error_deg",
    "parent",
    "short_ename",
    "ename",
    "uname",
)

_FLOAT_FIELDS = ("longitude", "latitude", "error_deg")
_SITE_KEEP = (
    "code",
    "ucode",
    "site_type",
    "state_code",
    "t_start",
    "t_stop",
    "short_name",
    "name",
    "location",
    "parent",
    "site_group",
)
_PAD_KEEP = (
    "site",
    "code",
    "ucode",
    "t_start",
    "t_stop",
    "short_name",
    "name",
    "location",
    "parent",
)


def _clean(val: str | None) -> str | None:
    """Strip whitespace; treat empty and the bare "-" sentinel as None."""
    if val is None:
        return None
    val = val.strip()
    if not val or val == "-":
        return None
    return val


class LaunchSiteIngestor:
    BATCH = 5_000

    def __init__(self, download_dir: Path):
        self.session = get_session()
        gcat = download_dir / "sources" / "position" / "gcat"
        self.sites_path = gcat / "sites.tsv"
        self.pads_path = gcat / "lp.tsv"
        self.malformed = 0
        self.unparsed_numbers = 0

    def _parse(
        self,
        path: Path,
        columns: tuple[str, ...],
        keep: tuple[str, ...],
        key_fields: tuple[str, ...],
    ) -> list[dict]:
        # A GCAT phase code is unique per table, so first row wins on the rare
        # repeat rather than silently overwriting a differently-dated row.
        by_key: dict[tuple[str, ...], dict] = {}
        with open(path, newline="") as f:
            for raw in csv.reader(f, delimiter="\t"):
                if not raw or raw[0].startswith("#"):
                    continue
                if len(raw) != len(columns):
                    self.malformed += 1
                    continue
                fields = {col: _clean(val) for col, val in zip(columns, raw)}
                key = tuple(fields[k] or "" for k in key_fields)
                if not all(key) or key in by_key:
                    continue
                row: dict[str, object] = {k: fields[k] for k in keep}
                for k in _FLOAT_FIELDS:
                    row[k] = self._to_float(fields[k])
                by_key[key] = row
        return list(by_key.values())

    def _to_float(self, val: str | None) -> float | None:
        if val is None:
            return None
        try:
            return float(val)
        except ValueError:
            self.unparsed_numbers += 1
            return None

    def _insert(self, model: type, rows: list[dict]) -> None:
        for i in range(0, len(rows), self.BATCH):
            self.session.execute(insert(model), rows[i : i + self.BATCH])
        self.session.commit()

    def run(self) -> None:
        if not self.sites_path.exists() or not self.pads_path.exists():
            logger.warning(
                "GCAT site tables not found at %s, skipping", self.sites_path.parent
            )
            return
        self.session.execute(delete(LaunchPad))
        self.session.execute(delete(LaunchSite))
        self.session.commit()

        sites = self._parse(self.sites_path, SITE_COLUMNS, _SITE_KEEP, ("code",))
        pads = self._parse(self.pads_path, PAD_COLUMNS, _PAD_KEEP, ("site", "code"))
        self._insert(LaunchSite, sites)
        self._insert(LaunchPad, pads)

        located = sum(1 for r in sites if r["latitude"] is not None)
        pads_located = sum(1 for r in pads if r["latitude"] is not None)
        logger.info(
            "Ingested %d launch sites (%d located) and %d pads (%d located)",
            len(sites),
            located,
            len(pads),
            pads_located,
        )
        if self.malformed:
            logger.warning("Skipped %d malformed GCAT site/pad rows", self.malformed)
        if self.unparsed_numbers:
            logger.warning(
                "%d GCAT site/pad coordinates could not be parsed",
                self.unparsed_numbers,
            )


def ingest(download_dir: Path) -> None:
    LaunchSiteIngestor(download_dir).run()
