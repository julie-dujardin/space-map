"""Download the SIMBAD records of the objects that are not single stars.

SIMBAD gives each object one main type. The types form a tree. This provider
keeps the objects whose main type is in FAMILIES or below one of them:
galaxies and their groupings, the interstellar medium, star clusters and
associations, stellar remnants, interacting binaries, and transient events.

SIMBAD has no bulk file, so the rows come from its TAP service. A synchronous
answer stops at MAX_ROWS, so each table is read in windows of object id. A
window that reaches the limit is split in two.

SIMBAD changes each day, so one export is one pass. An interrupted export
continues for RESUME_DAYS. After that, and on each new export, the windows on
disk are deleted first. Each table is then compared with a count by SIMBAD.

Writes, below sources/catalogues/simbad/:
- otypedef.csv                  the type tree
- basic/<first>-<last>.csv.gz   position, motion, redshift, size, main type
- ident/…                       every identifier of each object
- otypes/…                      every type of each object
- mesDistance/…                 distance measurements
- allfluxes/…                   magnitudes
- h_link/…                      parent and child links, for all of SIMBAD
- export.json                   the export in progress
- metadata.json

Licence: ODbL. https://simbad.cds.unistra.fr/simbad/
"""

import csv
import gzip
import io
import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError, Downloader
from space_map_data.download.providers.catalogues.fetch import post_lines_gz
from space_map_data.download.providers.exoplanets.simbad import TAP_URL
from space_map_data.download.providers.exoplanets.tap import tap_rows, tap_sync
from space_map_data.utils.paths import SOURCES_CATALOGUES_DIR

logger = logging.getLogger(__name__)

OUT_DIR = SOURCES_CATALOGUES_DIR / "simbad"
OTYPEDEF_FILE = "otypedef.csv"
STATE_FILE = "export.json"

MAX_ROWS = 2_000_000
WINDOW_OIDS = 500_000
RESUME_DAYS = 2
# SIMBAD changes while the export runs. This share of the rows can go missing.
COUNT_TOLERANCE = 0.001

# Nodes of the SIMBAD type tree, by type code.
FAMILIES = frozenset(
    {
        # Galaxies, active nuclei, and sets of galaxies.
        "G",
        "IG",
        "PaG",
        "GrG",
        "ClG",
        "PCG",
        "SCG",
        "PoG",
        "vid",
        # Interstellar medium, planetary nebulae, outflows.
        "ISM",
        "PoC",
        "PN",
        "out",
        # Star clusters, associations, streams.
        "Cl*",
        "As*",
        # Stellar remnants and interacting binaries.
        "WD*",
        "HS*",
        "N*",
        "XB*",
        "CV*",
        "Sy*",
        "ULX",
        # Black holes, lenses, and events.
        "grv",
        "gam",
        "SN*",
        "rB",
        "ev",
    }
)


@dataclass(frozen=True)
class Table:
    """The rows to keep of one SIMBAD table."""

    # The alias whose columns are exported.
    alias: str
    # FROM and WHERE of the kept rows. `{types}` is the list of kept types.
    rows: str
    # The object id that the windows cut.
    oid: str


_KEPT = "b.otype IN ({types})"


def _joined(table: str) -> Table:
    return Table(
        "t", f"{table} AS t JOIN basic AS b ON b.oid = t.oidref WHERE {_KEPT}", "b.oid"
    )


TABLES: dict[str, Table] = {
    "basic": Table("b", f"basic AS b WHERE {_KEPT}", "b.oid"),
    "ident": _joined("ident"),
    "otypes": _joined("otypes"),
    "mesDistance": _joined("mesDistance"),
    "allfluxes": _joined("allfluxes"),
    "h_link": Table("t", "h_link AS t WHERE t.child IS NOT NULL", "t.child"),
}


def kept_types(otypedef: str) -> list[str]:
    """The type codes in FAMILIES or below one of them, from `otypedef` CSV."""
    kept: list[str] = []
    found: set[str] = set()
    for row in csv.DictReader(io.StringIO(otypedef)):
        nodes = FAMILIES.intersection(node.strip() for node in row["path"].split(">"))
        if nodes:
            kept.append(row["otype"])
            found |= nodes
    if found != FAMILIES:
        raise DownloadError(f"SIMBAD type tree has no node {sorted(FAMILIES - found)}")
    return sorted(kept)


def count_rows(path: Path) -> int:
    with gzip.open(path) as file:
        return sum(1 for _ in file) - 1


def check_table(part: Path, lines: int) -> None:
    """Refuse an answer that is not a CSV table with a header."""
    with gzip.open(part, "rt") as file:
        head = file.readline().strip()
    if lines < 1 or not head or head.startswith("<"):
        raise DownloadError(f"SIMBAD sent no table: {head[:80]!r}")


class SimbadObjectsDownloader(Downloader):
    name = PROVIDERS.SIMBAD_OBJECTS

    def __init__(self, client: httpx.Client) -> None:
        super().__init__(client)
        self.out_dir = OUT_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        otypedef = tap_sync(self.client, TAP_URL, "SELECT * FROM otypedef")
        types = kept_types(otypedef)
        self._begin(types)
        (self.out_dir / OTYPEDEF_FILE).write_text(otypedef)
        quoted = ",".join("'" + code.replace("'", "''") + "'" for code in types)
        (last,) = self._first_row("SELECT MAX(oid) FROM basic")

        rows: dict[str, int] = {}
        for name, table in TABLES.items():
            kept = table.rows.format(types=quoted)
            rows[name] = sum(
                self._export(name, table, kept, first, first + WINDOW_OIDS - 1)
                for first in range(1, last + 1, WINDOW_OIDS)
            )
            logger.info("simbad %s: %d rows", name, rows[name])

        counted: dict[str, int] = {}
        for name, table in TABLES.items():
            kept = table.rows.format(types=quoted)
            (counted[name],) = self._first_row(f"SELECT COUNT(*) FROM {kept}")
            if rows[name] < counted[name] * (1 - COUNT_TOLERANCE):
                raise DownloadError(
                    f"SIMBAD export has {rows[name]} {name} rows, "
                    f"SIMBAD counts {counted[name]}"
                )
        self._save_metadata(
            TAP_URL,
            rows["basic"],
            complete=True,
            counted=counted,
            rows=rows,
            types=types,
        )
        (self.out_dir / STATE_FILE).unlink()

    def _begin(self, types: list[str]) -> None:
        """Continue the export in progress, or delete the windows and start one."""
        state_file = self.out_dir / STATE_FILE
        now = datetime.now(timezone.utc)
        if state_file.exists():
            state = json.loads(state_file.read_text())
            age = now - datetime.fromisoformat(state["started_at"])
            if state["types"] == types and age < timedelta(days=RESUME_DAYS):
                logger.info("simbad: the export of %s continues", state["started_at"])
                return
        # The record of the last export describes windows that now go away.
        self.metadata_file.unlink(missing_ok=True)
        for name in TABLES:
            if (self.out_dir / name).exists():
                logger.info("simbad: deleting the %s windows of the last export", name)
                shutil.rmtree(self.out_dir / name)
        state_file.write_text(
            json.dumps({"started_at": now.isoformat(), "types": types}, indent=2)
        )

    def _export(self, name: str, table: Table, kept: str, first: int, last: int) -> int:
        """Write one window of one table. Return its row count."""
        dest = self.out_dir / name / f"{first:08d}-{last:08d}.csv.gz"
        if dest.exists():
            logger.debug("simbad %s %d-%d: already on disk", name, first, last)
            return count_rows(dest)
        query = (
            f"SELECT {table.alias}.* FROM {kept} "
            f"AND {table.oid} BETWEEN {first} AND {last}"
        )
        lines = post_lines_gz(
            self.client, TAP_URL, dest, data=_window_form(query), check=check_table
        )
        if lines - 1 < MAX_ROWS:
            return lines - 1
        logger.info("simbad %s %d-%d: over the row limit, split", name, first, last)
        dest.unlink()
        middle = (first + last) // 2
        return self._export(name, table, kept, first, middle) + self._export(
            name, table, kept, middle + 1, last
        )

    def _first_row(self, query: str) -> list[int]:
        _, rows = tap_rows(self.client, TAP_URL, query)
        return [int(value) for value in rows[0]]


def _window_form(query: str) -> dict[str, str]:
    """The query form with the row limit of the service raised to its maximum."""
    return {
        "REQUEST": "doQuery",
        "LANG": "ADQL",
        "FORMAT": "csv",
        "MAXREC": str(MAX_ROWS),
        "QUERY": query,
    }
