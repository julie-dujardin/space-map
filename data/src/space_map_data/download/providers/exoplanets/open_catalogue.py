"""Download the Open Exoplanet Catalogue.

One gzip XML file. It nests planets in stars and stars in binaries, which the
tabular catalogues do not state.

Licence: MIT. https://github.com/OpenExoplanetCatalogue/open_exoplanet_catalogue
"""

import gzip
import logging
import xml.etree.ElementTree as ET
from datetime import timedelta

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError, Downloader
from space_map_data.utils.paths import SOURCES_EXOPLANETS_DIR

logger = logging.getLogger(__name__)

SYSTEMS_URL = (
    "https://github.com/OpenExoplanetCatalogue/oec_gzip/raw/master/systems.xml.gz"
)
OUT_DIR = SOURCES_EXOPLANETS_DIR / "open-exoplanet-catalogue"
SYSTEMS_FILE = "systems.xml.gz"


def count_objects(content: bytes) -> dict[str, int]:
    """Parse the gzip XML and count its systems, binaries, stars and planets."""
    root = ET.fromstring(gzip.decompress(content))
    if root.tag != "systems":
        raise DownloadError(f"Unexpected OEC root element <{root.tag}>")
    return {
        tag: sum(1 for _ in root.iter(tag))
        for tag in ("system", "binary", "star", "planet")
    }


class OpenExoplanetCatalogueDownloader(Downloader):
    name = PROVIDERS.OPEN_EXOPLANET_CATALOGUE
    # The repository is committed to daily. A week matches the other catalogues.
    max_age = timedelta(days=7)

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.out_dir = OUT_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        logger.info("Downloading Open Exoplanet Catalogue...")
        response = self.client.get(SYSTEMS_URL)
        response.raise_for_status()
        counts = count_objects(response.content)
        (self.out_dir / SYSTEMS_FILE).write_bytes(response.content)
        logger.info("  %s: %s", SYSTEMS_FILE, counts)
        self._save_metadata(SYSTEMS_URL, counts["planet"], complete=True, **counts)
