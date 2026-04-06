"""CLI entry point for: python -m space_map_data.ingest"""

import argparse
import logging
import logging.config
import tomllib

from space_map_data.utils.paths import DATA_DIR, DOWNLOAD_DIR
from space_map_data.utils.db import session_scope
from space_map_data.ingest.common import (
    ingest_bodies,
    ingest_features,
    ingest_wikidata,
    log_db_summary,
)
from space_map_data.ingest.providers.textures import TextureProcessor

ALL_TARGETS = ["bodies", "features", "wikidata", "textures"]


def cli():
    parser = argparse.ArgumentParser(description="Ingest space-map data into SQLite")
    parser.add_argument(
        "--targets",
        nargs="+",
        choices=[*ALL_TARGETS, "all"],
        default=["all"],
        metavar="TARGET",
        help=f"Targets to ingest: {', '.join(ALL_TARGETS)}, all (default: all)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Max records per source (for quick testing)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reprocess even if output already exists (textures)",
    )
    args = parser.parse_args()

    with open(DATA_DIR / "logging.toml", "rb") as f:
        logging.config.dictConfig(tomllib.load(f))

    selected = ALL_TARGETS if "all" in args.targets else args.targets

    with session_scope(create_db=True):
        if "bodies" in selected:
            ingest_bodies(DOWNLOAD_DIR, limit=args.limit)
        if "features" in selected:
            ingest_features(DOWNLOAD_DIR, limit=args.limit)
        if "wikidata" in selected:
            ingest_wikidata(DOWNLOAD_DIR, limit=args.limit)
        if "bodies" in selected or "features" in selected or "wikidata" in selected:
            log_db_summary()
        if "textures" in selected:
            TextureProcessor().process_all(force=args.force)


if __name__ == "__main__":
    cli()
