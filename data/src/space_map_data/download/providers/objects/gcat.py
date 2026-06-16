import json
import logging
from datetime import datetime, timezone

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError, Downloader
from space_map_data.utils.paths import SOURCES_POSITION_DIR

logger = logging.getLogger(__name__)

# Jonathan McDowell's GCAT orbital launch log — one row per payload, with
# launch vehicle, pad, site and flight/booster serial. https://planet4589.org/space/gcat/
LAUNCHLOG_URL = "https://planet4589.org/space/gcat/tsv/derived/launchlog.tsv"
EXPECTED_HEADER = "#Launch_Tag\t"


class GCATDownloader(Downloader):
    name = PROVIDERS.GCAT

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.out_dir = SOURCES_POSITION_DIR / "gcat"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def is_complete(self, limit: int | None) -> bool:
        # Refetched every UTC day; skip only if today is already done.
        if not self.metadata_file.exists():
            return False
        meta = json.loads(self.metadata_file.read_text())
        today = datetime.now(timezone.utc).date().isoformat()
        return meta.get("day") == today

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        logger.info("Downloading GCAT launch log...")
        response = self.client.get(LAUNCHLOG_URL)
        if response.status_code in (403, 404):
            raise DownloadError(
                f"HTTP {response.status_code} fetching launchlog — stopping (do not retry)"
            )
        response.raise_for_status()

        body = response.text
        if not body.startswith(EXPECTED_HEADER):
            raise DownloadError(f"Unexpected launchlog response: {body[:80]!r}")

        out_file = self.out_dir / "launchlog.tsv"
        out_file.write_text(body)
        # Two comment lines (header + "# Updated ...") precede the data rows.
        record_count = body.count("\n") - 2
        logger.info("Saved %s launchlog rows -> %s", f"{record_count:,}", out_file.name)

        today = datetime.now(timezone.utc).date()
        self._save_metadata(
            LAUNCHLOG_URL, record_count, complete=True, day=today.isoformat()
        )
