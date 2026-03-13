"""Space-map data downloader"""

import logging
import logging.config
import tomllib
from datetime import date
from pathlib import Path

import httpx

from .downloaders import Downloader
from .downloaders.celestrak import CelesTrakDownloader
from .downloaders.horizons import HorizonsDownloader
from .downloaders.sbdb import SBDBDownloader

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[2]
DOWNLOAD_DIR = DATA_DIR / "downloads"
USER_AGENT = "space-map/0.1 (github personal project)"

SOURCES: dict[str, tuple[type[Downloader], Path]] = {
    "celestrak": (CelesTrakDownloader, DOWNLOAD_DIR / "celes-trak"),
    "sbdb": (SBDBDownloader, DOWNLOAD_DIR / "sbdb"),
    "horizons": (HorizonsDownloader, DOWNLOAD_DIR / "horizons"),
}


def download_sources(
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
            cls, out_dir = SOURCES[name]
            downloader = cls(client, out_dir)
            if not force and downloader.is_complete(limit):
                logger.info("Skipping %s (already complete)", name)
                continue
            downloader.download(limit=limit, epoch=epoch)


def cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Download space-map data")
    parser.add_argument(
        "--sources",
        nargs="+",
        choices=[*SOURCES.keys(), "all"],
        default=["all"],
        metavar="SOURCE",
        help=f"Sources to download: {', '.join(SOURCES)}, all (default: all)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Max records/bodies per source (default: 50000)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if data is already complete",
    )
    args = parser.parse_args()

    with open(DATA_DIR / "logging.toml", "rb") as f:
        logging.config.dictConfig(tomllib.load(f))

    sources = None if "all" in args.sources else args.sources
    download_sources(sources=sources, limit=args.limit, force=args.force)
    logger.info("Done.")


if __name__ == "__main__":
    cli()
