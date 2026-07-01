"""Mirror the DAMIT lightcurve-inversion model database.

DAMIT (https://damit.cuni.cz, CC BY 4.0) publishes a monthly full export —
one tar.gz with every shape/spin file plus the CSV tables (asteroids, models,
references) that map models to asteroids and publications. We fetch the
archive whose versioned name the ``latest`` endpoint advertises, then extract
under ``bodies/lightcurve/damit/``. Ingest reads the extracted tree + CSVs
directly; per-asteroid permalinks are ``.../asteroids/view/<asteroid_id>``.
"""

import logging
import re
import shutil
import tarfile

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError, Downloader
from space_map_data.download.providers.three_d.resumable import download_resumable
from space_map_data.utils.paths import SOURCES_MODELS_BODIES_DIR

logger = logging.getLogger(__name__)

LATEST_URL = "https://damit.cuni.cz/projects/damit/exports/complete/latest"
TIER_DIR = SOURCES_MODELS_BODIES_DIR / "lightcurve"
EXTRACT_DIR = TIER_DIR / "damit"


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
        archive_name = self._latest_archive_name()
        archive = self.out_dir / archive_name
        extracted_marker = EXTRACT_DIR / ".extracted-from"

        if (
            extracted_marker.exists()
            and extracted_marker.read_text().strip() == archive_name
        ):
            logger.info("DAMIT %s already extracted", archive_name)
            return

        if not download_resumable(self.client, LATEST_URL, archive):
            raise DownloadError(f"DAMIT archive download failed: {archive_name}")

        self._extract(archive)
        extracted_marker.write_text(archive_name + "\n")
        for old in self.out_dir.glob("damit-*.tar.gz"):
            if old.name != archive_name:
                logger.info("removing superseded archive %s", old.name)
                old.unlink()
        self._save_metadata(LATEST_URL, 1, complete=True, archive=archive_name)

    def _latest_archive_name(self) -> str:
        resp = self.client.head(LATEST_URL, timeout=60.0)
        resp.raise_for_status()
        m = re.search(
            r'filename="([^"]+)"', resp.headers.get("content-disposition", "")
        )
        if not m:
            raise DownloadError("DAMIT latest endpoint sent no versioned filename")
        return m.group(1)

    def _extract(self, archive) -> None:
        """Extract into EXTRACT_DIR, stripping a single common root dir if any."""
        if EXTRACT_DIR.exists():
            shutil.rmtree(EXTRACT_DIR)
        EXTRACT_DIR.mkdir(parents=True)
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
                tar.extract(m, EXTRACT_DIR, filter="data")
        logger.info("extracted %d entries", len(members))
