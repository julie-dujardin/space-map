"""Download the NASA Exoplanet Archive tables.

Each table is taken whole, with every column. `pscomppars` has one row per
confirmed planet. `ps` and `stellarhosts` have one row per object per
publication. `toi`, `cumulative` and `k2pandc` hold the TESS, Kepler and K2
candidates.

Terms: the archive has no licence. It asks for its acknowledgement text and
for the DOI of each table used.
https://exoplanetarchive.ipac.caltech.edu/docs/acknowledge.html
"""

import csv
import logging
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError, Downloader
from space_map_data.download.providers.exoplanets.tap import tap_rows, tap_to_file
from space_map_data.utils.paths import SOURCES_EXOPLANETS_DIR

logger = logging.getLogger(__name__)

TAP_URL = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
OUT_DIR = SOURCES_EXOPLANETS_DIR / "nasa-exoplanet-archive"


@dataclass(frozen=True)
class ArchiveTable:
    """One TAP table.

    `columns` are the columns that the pipeline reads. The download fails if
    one is absent.
    """

    name: str
    columns: tuple[str, ...]
    description: str

    @property
    def filename(self) -> str:
        return f"{self.name}.csv"


# Columns that hold a catalogue id of the star, such as `HIP 1931`.
STAR_ID_COLUMNS = ("hd_name", "hip_name", "tic_id", "gaia_dr3_id", "gaia_dr2_id")

TABLES: tuple[ArchiveTable, ...] = (
    ArchiveTable(
        "pscomppars",
        ("pl_name", "hostname", "gaia_dr3_id"),
        "planets, one composite row each",
    ),
    ArchiveTable(
        "ps",
        ("pl_name", "hostname", "default_flag"),
        "planets, one row per publication",
    ),
    ArchiveTable(
        "stellarhosts",
        ("hostname", "sy_name", *STAR_ID_COLUMNS),
        "stars of planetary systems",
    ),
    ArchiveTable("toi", ("toi", "toipfx", "tid", "tfopwg_disp"), "TESS candidates"),
    ArchiveTable(
        "cumulative",
        ("kepoi_name", "kepler_name", "kepid", "koi_disposition"),
        "Kepler candidates",
    ),
    ArchiveTable(
        "k2pandc",
        (
            "pl_name",
            "k2_name",
            "epic_candname",
            "hostname",
            "epic_hostname",
            *STAR_ID_COLUMNS,
            "disposition",
        ),
        "K2 planets and candidates",
    ),
    ArchiveTable("ml", ("pl_name", "hostid"), "microlensing solutions"),
    ArchiveTable("keplernames", ("koi_name", "kepler_name", "pl_name"), "Kepler names"),
    ArchiveTable("k2names", ("epic_id", "k2_name", "pl_name"), "K2 names"),
    ArchiveTable("spectra", ("pl_name", "spec_path"), "atmospheric spectra index"),
    ArchiveTable("transitspec", ("plntname",), "transmission spectroscopy"),
    ArchiveTable("emissionspec", ("plntname",), "emission spectroscopy"),
)


def check_table(table: ArchiveTable, path: Path, expected_rows: int) -> None:
    """Fail on a missing column or on a row count other than `expected_rows`."""
    with path.open(newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, [])
        missing = [column for column in table.columns if column not in header]
        if missing:
            raise DownloadError(f"{table.name} has no column {', '.join(missing)}")
        rows = sum(1 for _ in reader)
    if rows != expected_rows:
        raise DownloadError(
            f"{table.name} has {rows} rows, the archive counts {expected_rows}"
        )


class ExoplanetArchiveDownloader(Downloader):
    name = PROVIDERS.EXOPLANET_ARCHIVE
    # The archive adds planets about once a week.
    max_age = timedelta(days=7)

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.out_dir = OUT_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def is_complete(self, limit: int | None) -> bool:
        # A table added to TABLES since the last run forces a refetch.
        return super().is_complete(limit) and all(
            (self.out_dir / table.filename).exists() for table in TABLES
        )

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        partials = {
            table: self.out_dir / f"{table.filename}.partial" for table in TABLES
        }
        try:
            counts = {
                table.name: self._fetch(table, partial)
                for table, partial in partials.items()
            }
            # Every table passes its check before one replaces an old file.
            for table, partial in partials.items():
                partial.replace(self.out_dir / table.filename)
        finally:
            for partial in partials.values():
                partial.unlink(missing_ok=True)
        self._save_metadata(
            TAP_URL, counts["pscomppars"], complete=True, table_record_counts=counts
        )

    def _fetch(self, table: ArchiveTable, path: Path) -> int:
        """Stream one table to `path` and check it. Return its row count."""
        logger.info("Downloading Exoplanet Archive %s...", table.description)
        _, count = tap_rows(self.client, TAP_URL, f"select count(*) from {table.name}")
        if len(count) != 1 or not count[0][0].isdigit():
            raise DownloadError(f"Unexpected row count of {table.name}: {count[:2]}")
        expected = int(count[0][0])
        tap_to_file(self.client, TAP_URL, f"select * from {table.name}", path)
        check_table(table, path, expected)
        logger.info(
            "  %s: %d rows, %.1f MB",
            table.filename,
            expected,
            path.stat().st_size / 1e6,
        )
        return expected
