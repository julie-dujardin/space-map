"""CLI entry point for: python -m space_map_data.ingest"""

import argparse
import logging
import logging.config
import tomllib

from space_map_data.utils.paths import DATA_DIR, DB_FILE, DOWNLOAD_DIR
from space_map_data.utils.db import session_scope
from space_map_data.ingest.common import (
    ingest_objects,
    ingest_features,
    ingest_wikidata,
    log_db_summary,
)
from space_map_data.ingest.providers.textures import TextureProcessor

ALL_TARGETS = ["objects", "features", "wikidata", "textures"]


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
        "--force",
        action="store_true",
        help="Reprocess even if output already exists (textures)",
    )
    args = parser.parse_args()

    with open(DATA_DIR / "logging.toml", "rb") as f:
        logging.config.dictConfig(tomllib.load(f))

    full_rebuild = "all" in args.targets
    selected = ALL_TARGETS if full_rebuild else args.targets

    if full_rebuild:
        for suffix in ("", "-wal", "-shm"):
            (DB_FILE.parent / f"{DB_FILE.name}{suffix}").unlink(missing_ok=True)
        logging.getLogger(__name__).info("Full rebuild: dropped %s", DB_FILE)

    with session_scope(create_db=True):
        if "objects" in selected:
            ingest_objects(DOWNLOAD_DIR)
        if "features" in selected:
            ingest_features(DOWNLOAD_DIR)
        if "wikidata" in selected:
            ingest_wikidata(DOWNLOAD_DIR)
        if "objects" in selected or "features" in selected or "wikidata" in selected:
            log_db_summary()
        if "textures" in selected:
            TextureProcessor().process_all(force=args.force)


if __name__ == "__main__":
    cli()
