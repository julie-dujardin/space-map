"""CLI entry point for: python -m space_map_data.download"""

import argparse
import logging
import logging.config
import tomllib

from space_map_data.download.common import SOURCES, download
from space_map_data.download.downloader import DATA_DIR

logger = logging.getLogger(__name__)


def cli():
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
    download(sources=sources, limit=args.limit, force=args.force)
    logger.info("Done.")


if __name__ == "__main__":
    cli()
