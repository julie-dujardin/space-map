import logging
import time
from posixpath import basename as url_basename
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from tqdm import tqdm

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import Downloader

logger = logging.getLogger(__name__)

DOWNLOAD_PAGE = "https://planetarynames.wr.usgs.gov/GIS_Downloads"
REQUEST_DELAY = 5


def _parse_download_links(html: str) -> dict[str, list[str]]:
    """Extract download URLs from the GIS Downloads page, grouped by body."""
    soup = BeautifulSoup(html, "html.parser")
    bodies: dict[str, list[str]] = {}
    for a in soup.select("a[href$='.zip'], a[href$='.kmz']"):
        url = str(a["href"])
        # Derive body name from the first path component of the filename.
        filename = url_basename(urlparse(url).path)
        body = filename.split("_nomenclature_")[0]
        bodies.setdefault(body, []).append(url)
    return bodies


class IAUNomenclatureDownloader(Downloader):
    name = PROVIDERS.IAU_NOMENCLATURE

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        logger.info("Fetching download page: %s", DOWNLOAD_PAGE)
        resp = self.client.get(DOWNLOAD_PAGE)
        resp.raise_for_status()

        bodies = _parse_download_links(resp.text)

        body_list = list(bodies.items())
        if limit is not None:
            body_list = body_list[:limit]

        logger.info("Found %d bodies to download", len(body_list))

        downloaded = 0
        skipped = 0
        errors = 0

        for body, file_urls in tqdm(body_list, desc="IAU Nomenclature"):
            body_dir = self.out_dir / body.lower()
            body_dir.mkdir(exist_ok=True)

            for url in file_urls:
                filename = url.rsplit("/", 1)[-1]
                out_path = body_dir / filename

                if out_path.exists():
                    skipped += 1
                    continue

                try:
                    r = self.client.get(url)
                    if r.status_code == 404:
                        logger.warning("404 for %s — skipping", url)
                        errors += 1
                        time.sleep(REQUEST_DELAY)
                        continue
                    r.raise_for_status()
                    out_path.write_bytes(r.content)
                    downloaded += 1
                except Exception:
                    logger.exception("Failed to download %s", url)
                    errors += 1

                time.sleep(REQUEST_DELAY)

        logger.info(
            "Done: %d downloaded, %d skipped (existing), %d errors",
            downloaded,
            skipped,
            errors,
        )
        self._save_metadata(
            DOWNLOAD_PAGE,
            downloaded + skipped,
            complete=limit is None or limit >= len(bodies),
        )
