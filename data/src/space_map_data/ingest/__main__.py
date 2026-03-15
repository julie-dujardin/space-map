"""CLI entry point for: python -m space_map_data.ingest"""

import argparse
import logging
import logging.config
import tomllib
from pathlib import Path

from space_map_data.utils.paths import DATA_DIR, DOWNLOAD_DIR
from space_map_data.ingest.common import ingest


def cli():
    parser = argparse.ArgumentParser(description="Ingest space-map data into SQLite")
    parser.add_argument(
        "--db",
        type=Path,
        default=DOWNLOAD_DIR / "space-map.db",
        metavar="PATH",
        help=f"Output database path (default: {DOWNLOAD_DIR / 'space-map.db'})",
    )
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

    ingest(args.db, DOWNLOAD_DIR, limit=args.limit)


if __name__ == "__main__":
    cli()
