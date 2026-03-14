"""Download orchestration — source registry and main download loop."""

import logging
from datetime import date

import httpx

from space_map_data.download.downloader import DOWNLOAD_DIR, Downloader
from space_map_data.download.providers.celestrak import CelesTrakDownloader
from space_map_data.download.providers.horizons import HorizonsDownloader
from space_map_data.download.providers.sbdb import SBDBDownloader

logger = logging.getLogger(__name__)

USER_AGENT = "space-map/0.1 (github personal project)"

SOURCES: dict[str, tuple[type[Downloader], str]] = {
    "celestrak": (CelesTrakDownloader, "celes-trak"),
    "sbdb": (SBDBDownloader, "sbdb"),
    "horizons": (HorizonsDownloader, "horizons"),
}


def download(
    sources: list[str] | None = None,
    limit: int | None = 50_000,
    *,
    force: bool = False,
    epoch: date | None = None,
) -> None:
    """Download data from the given sources (default: all)."""
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    selected = list(SOURCES.keys()) if sources is None else sources

    with httpx.Client(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=60.0,
    ) as client:
        for name in selected:
            cls, subdir = SOURCES[name]
            out_dir = DOWNLOAD_DIR / subdir
            downloader = cls(client, out_dir)
            if not force and downloader.is_complete(limit):
                logger.info("Skipping %s (already complete)", name)
                continue
            downloader.download(limit=limit, epoch=epoch)
