"""Download the 40 pc sample of white dwarfs of O'Brien et al. 2024.

Table A1 of the paper (MNRAS 527, 8687) lists the 1078 white dwarfs within
40 pc of the Sun, each with its Gaia DR3 source id. Most rows have the
paper's fit to the Gaia photometry: Teff, log g and mass with their errors.
The ingest takes these as paper values of the stars (`literature`).

The paper links the table as a CSV on the authors' server. VizieR's CfA
mirror does not hold the catalogue (J/MNRAS/527/8687).

Writes, below sources/stars/obrien-2024/:
- table_a1.csv   the table as published
- metadata.json  the row count and TERMS
"""

import csv
import io
import logging

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import Downloader, DownloadError
from space_map_data.utils.paths import SOURCES_STARS_DIR

logger = logging.getLogger(__name__)

OUT_DIR = SOURCES_STARS_DIR / "obrien-2024"
URL = "https://cygnus.astro.warwick.ac.uk/phrtxn/TableA1_full_sample.csv"
TABLE_FILE = "table_a1.csv"
# The columns that the ingest reads.
ID_COLUMN = "DR3_source_id"
FIT_COLUMNS = (
    "gaia_teff",
    "gaia_teff_err",
    "gaia_logg",
    "gaia_logg_err",
    "gaia_mass",
    "gaia_mass_err",
)
TERMS = {
    "license": "CC BY 4.0, the licence of the paper that publishes the table.",
    "terms_url": "https://doi.org/10.1093/mnras/stad3773",
    "distribution": "open",
    "citation": (
        "O'Brien, M. W., Tremblay, P.-E., Klein, B. L., et al. 2024, MNRAS,"
        " 527, 8687, 40 pc sample of white dwarfs from Gaia"
    ),
    "note": "The Teff, log g and mass are the authors' fit to Gaia photometry.",
}


class ObrienWhiteDwarfsDownloader(Downloader):
    name = PROVIDERS.OBRIEN_WHITE_DWARFS

    def __init__(self, client: httpx.Client) -> None:
        super().__init__(client)
        self.out_dir = OUT_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        response = self.client.get(URL, timeout=120.0, follow_redirects=True)
        if response.status_code != 200:
            raise DownloadError(f"HTTP {response.status_code} for {URL}")
        reader = csv.DictReader(io.StringIO(response.text))
        missing = {ID_COLUMN, *FIT_COLUMNS} - set(reader.fieldnames or ())
        if missing:
            raise DownloadError(f"{URL}: no column {sorted(missing)}")
        rows = sum(1 for _ in reader)
        part = self.out_dir / (TABLE_FILE + ".part")
        part.write_bytes(response.content)
        part.replace(self.out_dir / TABLE_FILE)
        logger.info("O'Brien et al. 2024: %d white dwarfs", rows)
        self._save_metadata(URL, rows, complete=True, terms=TERMS)
