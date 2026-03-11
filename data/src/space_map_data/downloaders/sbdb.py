import csv
import logging
import time

from tqdm import tqdm

from . import Downloader

logger = logging.getLogger(__name__)

URL = "https://ssd-api.jpl.nasa.gov/sbdb_query.api"
PAGE_SIZE = 500


class SBDBDownloader(Downloader):
    name = "sbdb"

    def _fetch_all_fields(self) -> list[str]:
        """Discover all available field names via the info endpoint."""
        response = self.client.get(URL, params={"info": "field"})
        response.raise_for_status()
        categories = response.json()["info"]["field"]
        return [f["name"] for cat in categories.values() for f in cat["list"]]

    def download(self, limit: int | None = None) -> None:
        out_file = self.out_dir / "small-bodies.csv"
        total_written = 0
        total_available = None

        logger.info("Fetching available fields...")
        all_fields = self._fetch_all_fields()
        logger.info("%d fields available", len(all_fields))

        with out_file.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(all_fields)
            bar = tqdm(total=None, unit="obj", desc="SBDB", dynamic_ncols=True)

            offset = 0
            while True:
                remaining = None if limit is None else limit - total_written
                if remaining is not None and remaining <= 0:
                    break

                params = {
                    "fields": ",".join(all_fields),
                    "limit": min(PAGE_SIZE, remaining)
                    if remaining is not None
                    else PAGE_SIZE,
                    "limit-from": offset,
                    "full-prec": "true",
                }

                response = self.client.get(URL, params=params)
                response.raise_for_status()
                payload = response.json()

                if total_available is None:
                    total_available = payload["count"]
                    bar.total = (
                        min(total_available, limit) if limit else total_available
                    )
                    bar.refresh()

                rows = payload.get("data") or []
                if not rows:
                    break

                writer.writerows(rows)
                total_written += len(rows)
                offset += len(rows)
                bar.update(len(rows))

                if len(rows) < PAGE_SIZE:
                    break

                time.sleep(0.5)

            bar.close()

        logger.info(
            "Saved %s records -> %s",
            f"{total_written:,}",
            out_file.relative_to(self.out_dir),
        )
        self._save_metadata(
            URL, total_written, complete=total_written == total_available
        )
