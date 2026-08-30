import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError, Downloader
from pathlib import Path

from space_map_data.utils.paths import SOURCES_POSITION_DIR

logger = logging.getLogger(__name__)

GCAT_BASE = "https://planet4589.org/space/gcat/tsv"


@dataclass(frozen=True)
class GCATTable:
    """One GCAT TSV. ``header`` is checked so a redesigned column set fails the
    download rather than reaching the parsers as silently different data."""

    filename: str
    path: str
    header: str
    description: str


# Jonathan McDowell's GCAT. https://planet4589.org/space/gcat/
#
# The launch log and lv.tsv drive the launch-vehicle group pages. The four
# tables below back the spacecraft catalogue instead: GCAT is the only
# compilation that states launch mass, dry mass, thrust and Isp for most flown
# hardware in one place and with one set of unit conventions, which is what a Δv
# derived from the rocket equation needs — a launch mass from a press kit and a
# dry mass from an encyclopedia will not subtract to a propellant load.
TABLES: tuple[GCATTable, ...] = (
    GCATTable(
        "launchlog.tsv",
        "derived/launchlog.tsv",
        "#Launch_Tag\t",
        "orbital launch log",
    ),
    GCATTable(
        "lv.tsv",
        "tables/lv.tsv",
        "#LV_Name\t",
        "launch-vehicle table",
    ),
    GCATTable(
        "lvs.tsv",
        "tables/lvs.tsv",
        "#LV_Name\t",
        "launch-vehicle stage stacks",
    ),
    GCATTable(
        "stages.tsv",
        "tables/stages.tsv",
        "#Stage_Name\t",
        "stage masses",
    ),
    GCATTable(
        "engines.tsv",
        "tables/engines.tsv",
        "#Name\t",
        "engine thrust & Isp",
    ),
    # Launch and dry mass per catalogued object. `Mass - DryMass` is the
    # propellant the spacecraft flew with, which no other source states
    # directly.
    GCATTable(
        "satcat.tsv",
        "cat/satcat.tsv",
        "#JCAT\t",
        "satellite catalogue",
    ),
    # Where launches leave from. Both tables carry a position and its stated
    # uncertainty, which is what lets a site be placed on the globe at all —
    # the launchlog names sites and pads only by code. `lp.tsv` is the finer
    # of the two: a site row is one coarse point for a whole range, a launch
    # point is the individual pad.
    GCATTable(
        "sites.tsv",
        "tables/sites.tsv",
        "#Site\t",
        "launch sites",
    ),
    GCATTable(
        "lp.tsv",
        "tables/lp.tsv",
        "#Site\t",
        "launch points (pads)",
    ),
)


def fetch_gcat_table(
    client: httpx.Client, base_url: str, table: GCATTable, out_dir: Path
) -> int:
    """Fetch one GCAT TSV and write it to ``out_dir``. Returns the row count.

    The header check is the contract with the publisher: a redesigned column
    set fails here rather than reaching the parsers as silently different
    data. Shared with the Deep Space Catalog, which is a separate publication
    on the same site with the same conventions."""
    url = f"{base_url}/{table.path}"
    response = client.get(url)
    if response.status_code in (403, 404):
        raise DownloadError(
            f"HTTP {response.status_code} fetching {table.filename} — stopping (do not retry)"
        )
    response.raise_for_status()

    body = response.text
    if not body.startswith(table.header):
        raise DownloadError(f"Unexpected {table.filename} response: {body[:80]!r}")

    (out_dir / table.filename).write_text(body)
    return sum(1 for line in body.splitlines() if line and not line.startswith("#"))


class GCATDownloader(Downloader):
    name = PROVIDERS.GCAT

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.out_dir = SOURCES_POSITION_DIR / "gcat"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def is_complete(self, limit: int | None) -> bool:
        # Refetched every UTC day; skip only if today is already done. A table
        # added since the last run also forces a refetch, so the new file
        # appears without waiting for tomorrow.
        if not self.metadata_file.exists():
            return False
        meta = json.loads(self.metadata_file.read_text())
        if meta.get("day") != datetime.now(timezone.utc).date().isoformat():
            return False
        return all((self.out_dir / table.filename).exists() for table in TABLES)

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        counts = {table.filename: self._download_table(table) for table in TABLES}

        today = datetime.now(timezone.utc).date()
        self._save_metadata(
            f"{GCAT_BASE}/",
            counts["launchlog.tsv"],
            complete=True,
            day=today.isoformat(),
            table_record_counts=counts,
        )

    def _download_table(self, table: GCATTable) -> int:
        logger.info("Downloading GCAT %s...", table.description)
        rows = fetch_gcat_table(self.client, GCAT_BASE, table, self.out_dir)
        logger.info("  %s: %d rows", table.filename, rows)
        return rows
