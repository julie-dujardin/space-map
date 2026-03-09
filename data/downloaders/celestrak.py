import csv
import logging
import sys
from io import StringIO

from . import Downloader

logger = logging.getLogger(__name__)

URL = "https://celestrak.org/NORAD/elements/gp.php"


class CelesTrakDownloader(Downloader):
    name = "celestrak"

    def download(self, limit: int | None = None) -> dict:
        out_file = self.out_dir / "gp-active.csv"
        url = f"{URL}?GROUP=active&FORMAT=csv"

        logger.info("Downloading active GP elements...")
        response = self.client.get(url)

        if response.status_code in (403, 404):
            logger.error("HTTP %d — stopping (do not retry)", response.status_code)
            sys.exit(1)

        response.raise_for_status()

        # Limit is ignored, celestrak always return everything.
        out_file.write_bytes(response.content)
        record_count = response.text.count("\n") - 1

        logger.info(
            "Saved %s records -> %s",
            f"{record_count:,}",
            out_file.relative_to(self.out_dir),
        )
        return self._metadata(url, record_count)
