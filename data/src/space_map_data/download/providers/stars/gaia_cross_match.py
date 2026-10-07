"""Download the Gaia tables that join Gaia sources to Hipparcos stars.

The cross-matches were made for Gaia EDR3. DR3 has the same source list, so
they hold for DR3 and stay in the EDR3 tree.

Writes, below sources/stars/gaia/gedr3/cross_match/:
- hipparcos2_best_neighbour/   the best Gaia source for each Hipparcos star
- hipparcos2_neighbourhood/    every Gaia source near each Hipparcos star
- metadata.json
Each table keeps its files as published, with `_MD5SUM.txt` and the notes.

Licence: CC BY-NC 3.0 IGO, credit ESA/Gaia/DPAC.
https://www.cosmos.esa.int/web/gaia-users/license
"""

import hashlib
import logging

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import Downloader
from space_map_data.download.providers.stars.gaia_bulk import (
    BULK_URL,
    OUT_DIR,
    fetch_md5sums,
    fetch_note,
    fetch_verified,
)

logger = logging.getLogger(__name__)

TREE = "gedr3/cross_match"
TABLES = ("hipparcos2_best_neighbour", "hipparcos2_neighbourhood")
NOTES = ("_citation.txt", "_disclaimer.txt")


class GaiaCrossMatchDownloader(Downloader):
    name = PROVIDERS.GAIA_CROSS_MATCH

    def __init__(self, client: httpx.Client) -> None:
        super().__init__(client)
        self.out_dir = OUT_DIR / TREE
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        tables: dict[str, dict[str, str]] = {}
        for table in TABLES:
            table_url = f"{BULK_URL}/{TREE}/{table}/"
            table_dir = self.out_dir / table
            table_dir.mkdir(exist_ok=True)
            sums = fetch_md5sums(self.client, table_url, table_dir)
            for name, md5 in sums.items():
                dest = table_dir / name
                if dest.exists() and hashlib.md5(dest.read_bytes()).hexdigest() == md5:
                    logger.info("%s/%s: already on disk", table, name)
                    continue
                dest.write_bytes(fetch_verified(self.client, table_url + name, md5))
                logger.info("%s/%s: %d bytes", table, name, dest.stat().st_size)
            for note in NOTES:
                (table_dir / note).write_bytes(
                    fetch_note(self.client, table_url + note)
                )
            tables[table] = sums

        self._save_metadata(
            f"{BULK_URL}/{TREE}/",
            sum(len(sums) for sums in tables.values()),
            complete=True,
            tables=tables,
        )
