"""CLI entry point for: space-map-export"""

import argparse
import logging
import logging.config
import tomllib

from space_map_data.export.common import export
from space_map_data.utils.db import session_scope
from space_map_data.utils.paths import DATA_DIR


def cli():
    parser = argparse.ArgumentParser(
        description="Export space-map data to static files"
    )
    parser.add_argument(
        "--limit-asteroids",
        type=int,
        default=10_000,
        metavar="N",
        help="Max unnamed asteroids in zoom 3 (0 = no limit, default: 10000)",
    )
    args = parser.parse_args()

    with open(DATA_DIR / "logging.toml", "rb") as f:
        logging.config.dictConfig(tomllib.load(f))

    limit = args.limit_asteroids if args.limit_asteroids > 0 else None
    with session_scope() as session:
        export(session, limit_asteroids=limit)


if __name__ == "__main__":
    cli()
