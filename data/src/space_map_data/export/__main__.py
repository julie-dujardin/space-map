"""CLI entry point for: space-map-export"""

import argparse
import logging
import logging.config
import tomllib

from space_map_data.export.pipeline.orchestrator import export
from space_map_data.utils.db import engine_scope
from space_map_data.utils.paths import DATA_DIR


def cli():
    parser = argparse.ArgumentParser(
        description="Export space-map data to static files"
    )
    parser.parse_args()

    with open(DATA_DIR / "logging.toml", "rb") as f:
        logging.config.dictConfig(tomllib.load(f))

    with engine_scope() as engine:
        export(engine)


if __name__ == "__main__":
    cli()
