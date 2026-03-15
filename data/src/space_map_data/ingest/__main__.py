"""CLI entry point for: python -m space_map_data.ingest"""

import argparse
import logging
import logging.config
import tomllib

from space_map_data.utils.paths import DATA_DIR, DOWNLOAD_DIR
from space_map_data.ingest.common import ingest


def cli():
    parser = argparse.ArgumentParser(description="Ingest space-map data into SQLite")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Max records per source (for quick testing)",
    )
    args = parser.parse_args()

    with open(DATA_DIR / "logging.toml", "rb") as f:
        logging.config.dictConfig(tomllib.load(f))

    ingest(DOWNLOAD_DIR, limit=args.limit)


if __name__ == "__main__":
    cli()
