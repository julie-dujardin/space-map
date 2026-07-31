"""Download SsODNet's Big Flat Table — one row per asteroid, best estimates.

SsODNet (IMCCE) aggregates published physical properties from thousands of
papers and picks a best estimate per object. We take it for the taxonomic
class: 171k asteroids carry one here against ~2k in SBDB's own `spec_B`/
`spec_T` columns, which is the difference between "a handful of famous
asteroids" and "most of what we draw".

The file is regenerated upstream in place, so `latest` in the name is the
whole versioning scheme — hence the age-based refresh.
"""

import logging
from datetime import timedelta

import httpx
import pyarrow.parquet as pq

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError, Downloader
from space_map_data.utils.paths import SOURCES_POSITION_DIR

logger = logging.getLogger(__name__)

BFT_URL = "https://ssp.imcce.fr/data/ssoBFT-latest_Asteroid.parquet"

# The upstream file is ~810 MB; anything far below that is a truncated body or
# an error page, not a table.
MIN_BYTES = 500_000_000


class SsODNetDownloader(Downloader):
    name = PROVIDERS.SSODNET
    # New taxonomies land with each survey release, not weekly.
    max_age = timedelta(days=30)

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.out_dir = SOURCES_POSITION_DIR / "ssodnet"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    @property
    def bft_file(self):
        return self.out_dir / "ssoBFT-latest_Asteroid.parquet"

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        logger.info("Downloading SsODNet BFT (~810 MB)...")
        # Written beside the target and moved on success, so a failed run
        # cannot leave a half-file that parses as a short table.
        partial = self.bft_file.with_suffix(".partial")
        written = 0
        with self.client.stream("GET", BFT_URL, timeout=600.0) as response:
            if response.status_code in (403, 404):
                raise DownloadError(f"HTTP {response.status_code} — stopping")
            response.raise_for_status()
            with partial.open("wb") as fh:
                for chunk in response.iter_bytes(chunk_size=1 << 20):
                    fh.write(chunk)
                    written += len(chunk)

        if written < MIN_BYTES:
            partial.unlink(missing_ok=True)
            raise DownloadError(f"BFT is {written} bytes, expected >{MIN_BYTES}")

        # Reading the footer both counts the rows and proves the file parses,
        # which a byte count alone does not.
        rows = pq.ParquetFile(partial).metadata.num_rows
        partial.replace(self.bft_file)
        logger.info(
            "Wrote %s — %d rows, %.0f MB", self.bft_file.name, rows, written / 1e6
        )
        self._save_metadata(BFT_URL, rows, complete=True, bytes=written)
