"""Download the UltracoolSheet: ultracool dwarfs with their distances.

The UltracoolSheet lists over 4,000 dwarfs of spectral type M6 and later and
imaged exoplanets, with a distance from a parallax, else from photometry.
Many have no Gaia parallax, or none at all. The ingest takes their distances.

The sheet lives in a Google spreadsheet; its releases are on Zenodo. This
provider takes the main table of one release, which RECORD names.

Writes, below sources/stars/ultracoolsheet/:
- main.csv      the main table of the release
- record.json   the Zenodo record
- metadata.json

Licence: CC BY 4.0. Cite Best, Dupuy, Liu, Sanghi, Siverd & Zhang 2025, The
UltracoolSheet 2.1.0, Zenodo, doi:10.5281/zenodo.4169085, and the papers that
its columns name.
"""

import csv
import hashlib
import io
import json
import logging

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import Downloader, DownloadError
from space_map_data.utils.paths import SOURCES_STARS_DIR

logger = logging.getLogger(__name__)

OUT_DIR = SOURCES_STARS_DIR / "ultracoolsheet"
ZENODO_URL = "https://zenodo.org/api/records"
# Version 2.1.0 of 2025-07-03.
RECORD = 15802304
SOURCE_FILE = "UltracoolSheet - Main.csv"
MAIN_FILE, RECORD_FILE = "main.csv", "record.json"


class UltracoolSheetDownloader(Downloader):
    name = PROVIDERS.ULTRACOOLSHEET

    def __init__(self, client: httpx.Client) -> None:
        super().__init__(client)
        self.out_dir = OUT_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def is_complete(self, limit: int | None) -> bool:
        if not super().is_complete(limit):
            return False
        return json.loads(self.metadata_file.read_text()).get("record") == RECORD

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        response = self.client.get(f"{ZENODO_URL}/{RECORD}", timeout=120.0)
        if response.status_code != 200:
            raise DownloadError(f"HTTP {response.status_code} for Zenodo {RECORD}")
        try:
            entry = {f["key"]: f for f in response.json()["files"]}[SOURCE_FILE]
            url = entry["links"]["self"]
            expected = entry["checksum"].removeprefix("md5:")
        except (ValueError, KeyError, TypeError) as error:
            raise DownloadError(f"Zenodo {RECORD}: unexpected record") from error
        content = self.client.get(url, timeout=600.0, follow_redirects=True)
        content.raise_for_status()
        found = hashlib.md5(content.content).hexdigest()
        if found != expected:
            raise DownloadError(f"{SOURCE_FILE}: MD5 {found}, Zenodo lists {expected}")
        part = self.out_dir / (MAIN_FILE + ".part")
        part.write_bytes(content.content)
        part.replace(self.out_dir / MAIN_FILE)
        (self.out_dir / RECORD_FILE).write_bytes(response.content)
        rows = sum(1 for _ in csv.DictReader(io.StringIO(content.text)))
        logger.info("UltracoolSheet %d: %d rows", RECORD, rows)
        self._save_metadata(url, rows, complete=True, record=RECORD)
