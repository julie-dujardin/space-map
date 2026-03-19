"""CLI entry point for: space-map-export"""

import argparse
import logging
import logging.config
import tomllib

from space_map_data.export.common import export
from space_map_data.utils.db import session_scope
from space_map_data.utils.paths import DATA_DIR, EXPORT_DIR


def cli():
    parser = argparse.ArgumentParser(description="Export space-map data to static files")
    parser.add_argument(
        "--limit-asteroids",
        type=int,
        default=10_000,
        metavar="N",
        help="Max asteroids to include (default: 10000)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        metavar="DIR",
        help=f"Output directory (default: {EXPORT_DIR / 'v1'})",
    )
    args = parser.parse_args()

    with open(DATA_DIR / "logging.toml", "rb") as f:
        logging.config.dictConfig(tomllib.load(f))

    out_dir = args.output_dir if args.output_dir else EXPORT_DIR / "v1"

    with session_scope() as session:
        export(session, out_dir, limit_asteroids=args.limit_asteroids)


if __name__ == "__main__":
    cli()
