"""CLI entry point for: python -m space_map_data.ingest"""

import argparse
import logging
import logging.config
import time
import tomllib
from pathlib import Path

from space_map_data.extrasolar import stars
from space_map_data.ingest.common import (
    ingest_features,
    ingest_images,
    ingest_objects,
    ingest_wikidata,
    ingest_wikipedia,
    log_db_summary,
)
from space_map_data.ingest.providers.models import ModelProcessor
from space_map_data.ingest.providers.rings import RingProcessor
from space_map_data.ingest.providers.textures import TextureProcessor
from space_map_data.models.ingest_stamp import write_ingest_stamp
from space_map_data.skycultures import build as skycultures
from space_map_data.utils.db import get_session, session_scope
from space_map_data.utils.mirror import sync_all
from space_map_data.utils.paths import (
    DATA_DIR,
    DB_FILE,
    DOWNLOAD_DIR,
    REGISTRY_BACKUP_DIR,
    REGISTRY_ROOT,
)

TARGETS = [
    "objects",
    "features",
    "wikidata",
    "images",
    "wikipedia",
    "textures",
    "tiles",
    "rings",
    "models",
    "extrasolar",
    "skycultures",
]
# A tile build runs for days and replaces the public pyramids, and the
# extrasolar ingest mints IDs that never go away. The sky cultures read the
# registry that the extrasolar ingest writes. "all" leaves them out, so they
# run only when named.
NAMED_ONLY = {"tiles", "extrasolar", "skycultures"}
# Targets that write no DB rows. A run of only these leaves the DB and its
# ingest stamp alone, so the export keeps what it derived from the DB.
DB_FREE = {"extrasolar", "skycultures"}


def cli():
    parser = argparse.ArgumentParser(description="Ingest space-map data into SQLite")
    parser.add_argument(
        "--targets",
        nargs="+",
        choices=[*TARGETS, "all"],
        default=["all"],
        metavar="TARGET",
        help=f"Targets to ingest: {', '.join(TARGETS)}, all (default: all; "
        "all leaves out tiles, extrasolar and skycultures)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reprocess even if output already exists (textures, tiles, rings)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="extrasolar: read only the first Gaia chunks that hold this many"
        " stars; the ingest is partial, retires nothing and needs a"
        " --registry-root other than the default",
    )
    parser.add_argument(
        "--registry-root",
        type=Path,
        default=REGISTRY_ROOT,
        help=f"extrasolar: the registry to write (default: {REGISTRY_ROOT});"
        " another root backs up to <root>/backup. skycultures: the registry"
        " to read",
    )
    args = parser.parse_args()

    with open(DATA_DIR / "logging.toml", "rb") as f:
        logging.config.dictConfig(tomllib.load(f))

    full_rebuild = "all" in args.targets
    selected = [
        t
        for t in TARGETS
        if t in args.targets or (full_rebuild and t not in NAMED_ONLY)
    ]
    db_targets = [t for t in selected if t not in DB_FREE]
    if db_targets:
        ingest_db(db_targets, full_rebuild, args.force)
    if "extrasolar" in selected:
        backup = (
            REGISTRY_BACKUP_DIR
            if args.registry_root.resolve() == REGISTRY_ROOT.resolve()
            else args.registry_root / "backup"
        )
        result, summary = stars.ingest(args.registry_root, backup, args.limit)
        print(result.report)
        print(summary)
    if "skycultures" in selected:
        print(skycultures.ingest(args.registry_root))


def ingest_db(selected: list[str], full_rebuild: bool, force: bool) -> None:
    """Run the targets that write the DB, then stamp it."""
    sync_all()
    start_time = time.perf_counter()

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
        if "images" in selected:
            ingest_images()
        if "wikipedia" in selected:
            ingest_wikipedia()
        if any(
            t in selected
            for t in ("objects", "features", "wikidata", "images", "wikipedia")
        ):
            log_db_summary(start_time=start_time)
        if "textures" in selected:
            TextureProcessor().process_all(force=force)
        if "tiles" in selected:
            TextureProcessor().process_tiles(force=force)
        if "rings" in selected:
            RingProcessor().process_all(force=force)
        if "models" in selected:
            ModelProcessor().process_all(force=force)
        # Any of these targets can write DB rows (models updates
        # Object.model_name, textures flips map_texture_available, ...).
        write_ingest_stamp(get_session(), selected)


if __name__ == "__main__":
    cli()
