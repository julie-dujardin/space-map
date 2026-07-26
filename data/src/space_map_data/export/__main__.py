"""CLI entry point for: space-map-export"""

import argparse
import logging
import logging.config
import tomllib

from space_map_data.export.groups import export_groups_only
from space_map_data.export.nomenclature.quadrangles import export_quadrangles_only
from space_map_data.export.pipeline.orchestrator import export
from space_map_data.utils.db import engine_scope
from space_map_data.utils.paths import DATA_DIR


def cli():
    parser = argparse.ArgumentParser(
        description="Export space-map data to static files"
    )
    parser.add_argument(
        "--only",
        choices=("groups", "quadrangles"),
        default=None,
        help="Run only the named tier (additive — leaves other outputs untouched)",
    )
    args = parser.parse_args()

    with open(DATA_DIR / "logging.toml", "rb") as f:
        logging.config.dictConfig(tomllib.load(f))

    with engine_scope() as engine:
        if args.only == "groups":
            export_groups_only(engine)
        elif args.only == "quadrangles":
            export_quadrangles_only(engine)
        else:
            export(engine)


if __name__ == "__main__":
    cli()
