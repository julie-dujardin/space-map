"""Space-map data downloader"""

import json
import logging
import logging.config
import tomllib
from pathlib import Path

import httpx

from downloaders.celestrak import CelesTrakDownloader
from downloaders.horizons import HorizonsDownloader
from downloaders.sbdb import SBDBDownloader

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
METADATA_FILE = DOWNLOAD_DIR / "metadata.json"
USER_AGENT = "space-map/0.1 (github personal project)"

SOURCES = {
    "celestrak": (CelesTrakDownloader, DOWNLOAD_DIR / "celes-trak"),
    "sbdb": (SBDBDownloader, DOWNLOAD_DIR / "sbdb"),
    "horizons": (HorizonsDownloader, DOWNLOAD_DIR / "horizons"),
}


def update_metadata(results: dict) -> None:
    existing = {}
    if METADATA_FILE.exists():
        existing = json.loads(METADATA_FILE.read_text())
    existing.update(results)
    METADATA_FILE.write_text(json.dumps(existing, indent=2))
    logger.info("Metadata written -> metadata.json")


def download_sources(
    sources: list[str] | None = None,
    limit: int | None = 50_000,
) -> dict:
    """Download data from the given sources (default: all).

    Returns a dict of {source_name: metadata} for each downloaded source.
    """
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    selected = list(SOURCES.keys()) if sources is None else sources

    with httpx.Client(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=60.0,
    ) as client:
        results = {}
        for name in selected:
            cls, out_dir = SOURCES[name]
            downloader = cls(client, out_dir)
            results[name] = downloader.download(limit=limit)

        update_metadata(results)

    return results


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
        default=50_000,
        metavar="N",
        help="Max records/bodies per source (default: 50000)",
    )
    parser.add_argument(
        "--no-limit",
        dest="limit",
        action="store_const",
        const=None,
        help="Remove the row limit and download everything",
    )
    args = parser.parse_args()

    with open(BASE_DIR / "logging.toml", "rb") as f:
        logging.config.dictConfig(tomllib.load(f))

    sources = None if "all" in args.sources else args.sources
    download_sources(sources=sources, limit=args.limit)
    logger.info("Done.")


if __name__ == "__main__":
    cli()
