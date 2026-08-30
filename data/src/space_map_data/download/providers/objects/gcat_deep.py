"""Fetch Jonathan McDowell's Deep Space Catalog.

Separate from :mod:`.gcat` because it is a separate publication on a separate
URL with a separate cadence: the daily GCAT tables track the Earth-orbit
catalogue, while this is a versioned document revised every few years. The
object and phase tables are the only two published as TSV; Table III, the
per-object orbit provenance, is HTML and is read by hand when a solved
trajectory needs its source named.
"""

import logging
from datetime import timedelta

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import Downloader
from space_map_data.download.providers.objects.gcat import GCATTable, fetch_gcat_table
from space_map_data.probes.deepcat import DEEPCAT_DIR, OBJECTS_FILE, PHASES_FILE

logger = logging.getLogger(__name__)

DEEPCAT_BASE = "https://planet4589.org/space/deepcat"

TABLES: tuple[GCATTable, ...] = (
    GCATTable(OBJECTS_FILE, OBJECTS_FILE, "#DeepID\tStdID", "deep-space object table"),
    GCATTable(PHASES_FILE, PHASES_FILE, "#DeepID\tName", "mission phase table"),
)


class GCATDeepDownloader(Downloader):
    name = PROVIDERS.GCAT_DEEP

    # The catalogue is revised in named releases years apart, so a daily poll
    # would be noise against a file that does not move.
    max_age = timedelta(days=7)

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.out_dir = DEEPCAT_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def is_complete(self, limit: int | None) -> bool:
        return super().is_complete(limit) and all(
            (self.out_dir / t.filename).exists() for t in TABLES
        )

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        counts = {t.filename: self._download_table(t) for t in TABLES}
        self._save_metadata(
            f"{DEEPCAT_BASE}/",
            counts[PHASES_FILE],
            complete=True,
            table_record_counts=counts,
        )

    def _download_table(self, table: GCATTable) -> int:
        logger.info("Downloading Deep Space Catalog %s...", table.description)
        rows = fetch_gcat_table(self.client, DEEPCAT_BASE, table, self.out_dir)
        logger.info("  %s: %d rows", table.filename, rows)
        return rows


__all__ = ["DEEPCAT_BASE", "GCATDeepDownloader", "TABLES"]
