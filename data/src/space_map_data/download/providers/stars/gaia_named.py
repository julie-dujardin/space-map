"""Download the Gaia DR3 rows of the SIMBAD stars that gaia_source leaves out.

gaia_source keeps the stars with a parallax over 5 times its error. Many
famous stars have no such parallax: very bright or very red stars, stars in
the Magellanic Clouds, close binaries. This provider uploads the Gaia DR3 ids
of the simbad_stars list to the archive's TAP service and keeps the rows that
gaia_source leaves out, with the columns of gaia_source and their astrometric
fidelity where the fidelity table has a row.

Writes, below sources/stars/gaia/gdr3/named_stars/:
- gaia_source.parquet   the rows
- fidelity.parquet      their rows of external.gaiaedr3_spurious
- metadata.json

Licence: CC BY-NC 3.0 IGO, credit ESA/Gaia/DPAC. Fidelity: Rybizki et al.
2022, MNRAS 510, 2597.
https://www.cosmos.esa.int/web/gaia-users/license
"""

import csv
import json
import logging
import re
from pathlib import Path

import httpx
import pyarrow as pa

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.exoplanets.inputs import InputReader
from space_map_data.download.providers.stars import (
    gaia_bulk,
    gaia_fidelity,
    gaia_source,
    simbad_stars,
)
from space_map_data.download.providers.stars.gaia_bulk import ARROW_TYPES
from space_map_data.utils.files import write_parquet

logger = logging.getLogger(__name__)

TAP_URL = gaia_fidelity.TAP_URL
OUT_DIR = gaia_bulk.OUT_DIR / gaia_source.RELEASE / "named_stars"
SOURCE_FILE, FIDELITY_FILE = "gaia_source.parquet", "fidelity.parquet"
IDENT_FILE = simbad_stars.OUT_DIR / simbad_stars.IDENT_FILE
COLUMNS_FILE = gaia_bulk.OUT_DIR / gaia_source.TABLE_PATH / "columns.json"

_GAIA_ID = re.compile(r"Gaia DR3 (\d+)")
_SOURCE = (
    "select {columns} from TAP_UPLOAD.sent as u"
    " join gaiadr3.gaia_source as g on g.source_id = u.source_id"
    " where g.parallax_over_error is null or g.parallax_over_error <= {threshold}"
)


def simbad_gaia_ids(path: Path) -> list[int]:
    """The Gaia DR3 ids in the identifiers of the SIMBAD list, sorted."""
    with path.open(newline="") as handle:
        return sorted(
            {
                int(match[1])
                for row in csv.DictReader(handle)
                if (match := _GAIA_ID.fullmatch(row["id"].strip()))
            }
        )


def column_types(path: Path) -> dict[str, pa.DataType]:
    """The Arrow type of each gaia_source column, as the bulk files have it."""
    declared = {c["name"]: c["datatype"] for c in json.loads(path.read_text())}
    return {name: ARROW_TYPES[declared[name]] for name in gaia_source.COLUMNS}


class GaiaNamedStarsDownloader(InputReader):
    name = PROVIDERS.GAIA_NAMED_STARS
    inputs = (IDENT_FILE, COLUMNS_FILE)
    # Gaia DR3 does not change. The provider runs again when SIMBAD does.
    max_age = None

    def __init__(self, client: httpx.Client) -> None:
        super().__init__(client)
        self.out_dir = OUT_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        self.require_inputs()
        ids = simbad_gaia_ids(IDENT_FILE)
        if not ids:
            raise DownloadError(f"{IDENT_FILE} names no Gaia DR3 id")
        types = column_types(COLUMNS_FILE)
        query = _SOURCE.format(
            columns=", ".join(f"g.{name}" for name in gaia_source.COLUMNS),
            threshold=gaia_source.MIN_PARALLAX_OVER_ERROR,
        )
        logger.info("Asking Gaia for %d ids of the SIMBAD list...", len(ids))
        stars = gaia_fidelity.ask_ids(self.client, query, ids, types)
        found = stars["source_id"].to_pylist()
        fidelity = gaia_fidelity.ask_ids(
            self.client, gaia_fidelity.QUERY, sorted(found), gaia_fidelity.COLUMNS
        )
        logger.info(
            "%d of %d ids have no 5-sigma parallax, %d of them a fidelity row",
            stars.num_rows,
            len(ids),
            fidelity.num_rows,
        )
        for name, table in ((SOURCE_FILE, stars), (FIDELITY_FILE, fidelity)):
            write_parquet(table, self.out_dir / name)
        self._save_metadata(
            TAP_URL,
            stars.num_rows,
            complete=True,
            ids_sent=len(ids),
            fidelity_rows=fidelity.num_rows,
            min_parallax_over_error=gaia_source.MIN_PARALLAX_OVER_ERROR,
        )
