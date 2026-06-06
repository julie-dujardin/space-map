import csv
import json
import logging
import time

import httpx
from tqdm import tqdm

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import Downloader
from space_map_data.utils.paths import SOURCES_POSITION_DIR

logger = logging.getLogger(__name__)

URL = "https://ssd-api.jpl.nasa.gov/sbdb_query.api"
PAGE_SIZE = 5000
CHUNK_SIZE = 100_000


class SBDBDownloader(Downloader):
    name = PROVIDERS.SBDB

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.out_dir = SOURCES_POSITION_DIR / "sbdb"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    @property
    def _fields_file(self):
        return self.out_dir / "fields.json"

    def _fetch_all_fields(self) -> dict:
        """Discover all available field names via the info endpoint."""
        response = self.client.get(URL, params={"info": "field"})
        response.raise_for_status()
        return response.json()["info"]["field"]

    def _get_fields(self) -> list[str]:
        """Load cached fields from disk or fetch and save them."""
        fields = None
        if self._fields_file.exists():
            fields = json.loads(self._fields_file.read_text())
            logger.info("Loaded %d fields from %s", len(fields), self._fields_file.name)
        else:
            fields = self._fetch_all_fields()
            self._fields_file.write_text(json.dumps(fields, indent=4))
            logger.info("Fetched and saved %d fields", len(fields))
        return [f["name"] for cat in fields.values() for f in cat["list"]]

    def _open_chunk(self, chunk_start: int, fields: list[str]):
        """Open a new chunk file and write the header."""
        path = self.out_dir / f"small-bodies_{chunk_start}.csv"
        fh = path.open("w", newline="")
        writer = csv.writer(fh)
        writer.writerow(fields)
        return fh, writer, path

    def _close_chunk(self, fh, path, chunk_start: int, chunk_end: int):
        """Close and rename chunk file to include the end id."""
        fh.close()
        final = path.with_name(f"small-bodies_{chunk_start}_{chunk_end}.csv")
        path.rename(final)
        logger.info("Wrote chunk -> %s", final.name)

    def _existing_chunks(self) -> list[tuple[int, int]]:
        """Return sorted list of (start, end) for complete chunk files on disk."""
        chunks = []
        for p in self.out_dir.glob("small-bodies_*_*.csv"):
            parts = p.stem.split("_")
            if len(parts) == 3:
                chunks.append((int(parts[1]), int(parts[2])))
        chunks.sort()
        return chunks

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        total_available = None

        all_fields = self._get_fields()

        # Resume past existing complete chunks
        existing = self._existing_chunks()
        skip_to = 0
        for start, end in existing:
            if start == skip_to:
                skip_to = end + 1
            else:
                break
        if skip_to > 0:
            logger.info("Found existing chunks, resuming from offset %d", skip_to)

        # Delete any incomplete temp chunk files
        for p in self.out_dir.glob("small-bodies_*.csv"):
            if "_" not in p.stem.split("_", 1)[1]:
                p.unlink()

        total_written = skip_to
        chunk_start = skip_to
        chunk_written = 0
        fh, writer, chunk_path = self._open_chunk(chunk_start, all_fields)
        bar = tqdm(
            total=None, unit="obj", desc="SBDB", dynamic_ncols=True, initial=skip_to
        )

        try:
            offset = skip_to
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
                chunk_written += len(rows)
                offset += len(rows)
                bar.update(len(rows))

                if chunk_written >= CHUNK_SIZE:
                    self._close_chunk(
                        fh, chunk_path, chunk_start, chunk_start + chunk_written - 1
                    )
                    chunk_start += chunk_written
                    chunk_written = 0
                    fh, writer, chunk_path = self._open_chunk(chunk_start, all_fields)

                if len(rows) < PAGE_SIZE:
                    break

                time.sleep(5)
        finally:
            if chunk_written > 0:
                self._close_chunk(
                    fh, chunk_path, chunk_start, chunk_start + chunk_written - 1
                )
            else:
                fh.close()
                chunk_path.unlink(missing_ok=True)
            bar.close()

        logger.info(
            "Saved %s records total",
            f"{total_written:,}",
        )
        self._save_metadata(
            URL, total_written, complete=total_written == total_available
        )
