"""Mirror the DAMIT lightcurve-inversion model database.

DAMIT (https://damit.cuni.cz, CC BY 4.0) regenerates its full export DAILY —
one tar.gz with every shape/spin file plus the CSV tables (asteroids, models,
references) that map models to asteroids and publications. Some exports come
out cut short, with no tables, so ``latest`` cannot be trusted: we take the
newest whole export of the listing and swap it in only once its tables are
there. A freshness window keeps us from re-pulling 1.3 GB every day. Ingest
reads the extracted tree + CSVs directly; per-asteroid permalinks are
``.../asteroids/view/<asteroid_id>``.
"""

import logging
import re
import shutil
import tarfile
from datetime import UTC, datetime
from pathlib import Path

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import Downloader, DownloadError
from space_map_data.download.providers.three_d.resumable import download_resumable
from space_map_data.utils.paths import SOURCES_MODELS_BODIES_DIR

logger = logging.getLogger(__name__)

EXPORTS_URL = "https://damit.cuni.cz/projects/damit/exports"
TIER_DIR = SOURCES_MODELS_BODIES_DIR / "lightcurve"
EXTRACT_DIR = TIER_DIR / "damit"
MAX_ARCHIVE_AGE_DAYS = 30
# Whole exports differ by about 1%, and a cut one has lost half or more.
MIN_SHARE_OF_LARGEST = 0.9
_STAMP_RE = re.compile(r"damit-(\d{8}T\d{6}Z)")
_LISTED_RE = re.compile(r">(damit-\d{8}T\d{6}Z\.tar\.gz) \(([\d.]+) (MB|GB)\)<")
_MB_PER_UNIT = {"MB": 1, "GB": 1024}


def _archive_age_days(archive_name: str) -> float | None:
    m = _STAMP_RE.search(archive_name)
    if not m:
        return None
    stamp = datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    return (datetime.now(UTC) - stamp).total_seconds() / 86400


def whole_archive(page: str) -> str:
    """The name of the newest whole export on the export page, which lists the
    newest first."""
    listed = {
        name: float(size) * _MB_PER_UNIT[unit]
        for name, size, unit in _LISTED_RE.findall(page)
    }
    if not listed:
        raise DownloadError("DAMIT export page lists no archive")
    largest = max(listed.values())
    return next(
        name for name, mb in listed.items() if mb >= MIN_SHARE_OF_LARGEST * largest
    )


def has_tables(root: Path) -> bool:
    """True when an extracted export holds the tables that ingest reads."""
    return any(
        (candidate / "asteroid_models.csv").exists()
        and (candidate / "asteroids.csv").exists()
        for candidate in (root / "tables", root)
    )


class DAMITDownloader(Downloader):
    """Fetch and extract the DAMIT complete export."""

    name = PROVIDERS.DAMIT

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.out_dir = TIER_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def is_complete(self, limit: int | None) -> bool:
        # Always re-run; the HEAD check makes a fresh run cheap.
        return False

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        extracted_marker = EXTRACT_DIR / ".extracted-from"
        usable = extracted_marker.exists() and has_tables(EXTRACT_DIR)

        if usable:
            age = _archive_age_days(extracted_marker.read_text().strip())
            if age is not None and age < MAX_ARCHIVE_AGE_DAYS:
                logger.info(
                    "DAMIT extract is %.0f day(s) old — refresh skipped (< %d)",
                    age,
                    MAX_ARCHIVE_AGE_DAYS,
                )
                return

        archive_name = self._whole_archive_name()
        archive = self.out_dir / archive_name

        if usable and extracted_marker.read_text().strip() == archive_name:
            logger.info("DAMIT %s already extracted", archive_name)
            return

        url = f"{EXPORTS_URL}/complete/{archive_name}"
        if not download_resumable(self.client, url, archive):
            raise DownloadError(f"DAMIT archive download failed: {archive_name}")

        try:
            self._extract(archive)
        except (tarfile.TarError, EOFError, OSError) as e:
            # Corrupt bytes (e.g. resume across a server-side regeneration):
            # drop the archive so the next run redownloads instead of looping.
            archive.unlink(missing_ok=True)
            raise DownloadError(f"DAMIT archive corrupt, deleted: {e}") from e
        extracted_marker.write_text(archive_name + "\n")
        for old in self.out_dir.glob("damit-*.tar.gz"):
            if old.name != archive_name:
                logger.info("removing superseded archive %s", old.name)
                old.unlink()
        self._save_metadata(url, 1, complete=True, archive=archive_name)

    def _whole_archive_name(self) -> str:
        resp = self.client.get(EXPORTS_URL, timeout=60.0, follow_redirects=True)
        resp.raise_for_status()
        return whole_archive(resp.text)

    def _extract(self, archive: Path) -> None:
        """Replace EXTRACT_DIR with ``archive``, stripping a single common root
        dir if any. The extract in place survives an archive with no tables:
        ingest prunes every model of a tree it cannot read."""
        staging = EXTRACT_DIR.with_name(f"{EXTRACT_DIR.name}.new")
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        logger.info("extracting %s ...", archive.name)
        with tarfile.open(archive, "r:gz") as tar:
            members = tar.getmembers()
            roots = {m.name.split("/", 1)[0] for m in members}
            strip = len(roots) == 1 and all("/" in m.name or m.isdir() for m in members)
            for m in members:
                if strip:
                    if "/" not in m.name:
                        continue
                    m.name = m.name.split("/", 1)[1]
                tar.extract(m, staging, filter="data")
        logger.info("extracted %d entries", len(members))
        if not has_tables(staging):
            shutil.rmtree(staging)
            raise tarfile.ReadError(f"{archive.name} has no tables")
        if EXTRACT_DIR.exists():
            shutil.rmtree(EXTRACT_DIR)
        staging.rename(EXTRACT_DIR)
