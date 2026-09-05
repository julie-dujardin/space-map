"""Download Johnston's Archive "Asteroids with Satellites" pages.

The archive is the fullest census of asteroid and TNO companions there is —
it lists systems SBDB's ``sb-sat`` flag does not, and carries component
diameters, rotation, system masses and the discovery record, none of which
SBDB's satellite payload has at all.

Three index pages plus one page per system. The per-object pages are HTML
only, so the whole set is mirrored and parsed at ingest.
"""

import logging
import re
import time
from datetime import timedelta

import httpx
from tqdm import tqdm

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError, Downloader
from space_map_data.utils.paths import SOURCES_POSITION_DIR

logger = logging.getLogger(__name__)

BASE_URL = "https://www.johnstonsarchive.net/astro/"
INDEX_PAGE = "asteroidmoons.html"
# Confidence ranking per system; the per-object pages don't carry it.
CONFIDENCE_PAGE = "asteroidmoonslist3.html"
# Reference codes ([D21a], [P07f], ...) used throughout the per-object pages.
SOURCES_PAGE = "amsources.html"
INDEX_PAGES = (INDEX_PAGE, CONFIDENCE_PAGE, SOURCES_PAGE)

# The site returns 429 after roughly 60 pages at 0.35 s/request. 5 s is a 10x
# margin on the ~0.5 s that provoked it, and the walk is incremental anyway.
PER_REQUEST_DELAY_SECONDS = 5.0
# On a 429 the archive wants a real pause, not a retry.
BACKOFF_SECONDS = 120.0
MAX_ATTEMPTS = 3

_PAGE_RE = re.compile(r"astmoons/(am-[0-9A-Za-z_-]+)\.html")


class JohnstonDownloader(Downloader):
    name = PROVIDERS.JOHNSTON
    # Johnston updates within days of each new announcement; a fortnight keeps
    # the 560-page walk rare while staying close to current.
    max_age = timedelta(days=14)

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.out_dir = SOURCES_POSITION_DIR / "johnston"
        self.pages_dir = self.out_dir / "astmoons"
        self.pages_dir.mkdir(parents=True, exist_ok=True)

    def _get(self, path: str) -> str:
        """Fetch one page, pausing rather than hammering on a 429."""
        for attempt in range(MAX_ATTEMPTS):
            response = self.client.get(BASE_URL + path)
            if response.status_code == 429:
                logger.warning(
                    "Johnston rate-limited on %s, waiting %.0fs", path, BACKOFF_SECONDS
                )
                time.sleep(BACKOFF_SECONDS)
                continue
            response.raise_for_status()
            return response.text
        raise DownloadError(f"Johnston kept rate-limiting {path}, stopping")

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        index_html = self._get(INDEX_PAGE)
        (self.out_dir / INDEX_PAGE).write_text(index_html)
        for page in INDEX_PAGES[1:]:
            time.sleep(PER_REQUEST_DELAY_SECONDS)
            (self.out_dir / page).write_text(self._get(page))

        pages = sorted(set(_PAGE_RE.findall(index_html)))
        if not pages:
            raise DownloadError("Johnston index lists no object pages — layout changed")
        logger.info("Johnston index lists %d systems", len(pages))

        to_fetch = [
            p for p in pages if not self._is_fresh(self.pages_dir / f"{p}.html")
        ]
        fresh = len(pages) - len(to_fetch)
        if fresh:
            logger.info("%d Johnston pages still fresh, skipping", fresh)
        if limit is not None and len(to_fetch) > limit:
            to_fetch = to_fetch[:limit]
        if to_fetch:
            logger.info(
                "Fetching %d pages at %.0fs each (~%.0f min)",
                len(to_fetch),
                PER_REQUEST_DELAY_SECONDS,
                len(to_fetch) * PER_REQUEST_DELAY_SECONDS / 60,
            )

        failed = 0
        for page in tqdm(
            to_fetch, desc="Johnston systems", unit="page", dynamic_ncols=True
        ):
            try:
                body = self._get(f"astmoons/{page}.html")
            except DownloadError:
                raise
            except Exception as exc:
                logger.warning("Failed to fetch Johnston page %s: %s", page, exc)
                failed += 1
                continue
            (self.pages_dir / f"{page}.html").write_text(body)
            time.sleep(PER_REQUEST_DELAY_SECONDS)

        on_disk = sum(1 for p in pages if (self.pages_dir / f"{p}.html").exists())
        self._save_metadata(
            BASE_URL + INDEX_PAGE,
            on_disk,
            complete=on_disk == len(pages),
            systems_listed=len(pages),
            failed=failed,
        )
