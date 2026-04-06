"""One-time migration: move QIDs from entities/ into objects/ or nomenclature/.

Reads the id-resolver CSVs to determine which QIDs are IAU nomenclature
(P2824) vs space objects (everything else), then moves the corresponding
JSON files.  Anything left in entities/ is not touched.

Usage:
    python -m space_map_data.download.providers.wikidata.migrate_entities [--dry-run]
"""

import argparse
import csv
import io
import logging
import shutil
from pathlib import Path

from space_map_data.constants.providers import ID_TYPE_TO_WIKIDATA_PID, ID_TYPES
from space_map_data.utils.paths import DOWNLOAD_DIR

logger = logging.getLogger(__name__)

_NOMENCLATURE_PID = ID_TYPE_TO_WIKIDATA_PID[ID_TYPES.IAU_FEATURE_ID]  # P2824


def _read_qids_from_csv(csv_path: Path) -> set[str]:
    """Read all QIDs from a resolver CSV file."""
    if not csv_path.exists():
        return set()
    qids: set[str] = set()
    for row in csv.reader(io.StringIO(csv_path.read_text())):
        if len(row) > 1 and row[1]:
            qids.update(row[1].split())
    return qids


def migrate(*, dry_run: bool = False) -> None:
    wikidata_dir = DOWNLOAD_DIR / "wikidata"
    entities_dir = wikidata_dir / "entities"
    ids_dir = wikidata_dir / "ids"

    if not entities_dir.exists():
        logger.info("No entities/ directory found, nothing to migrate")
        return

    # Collect nomenclature QIDs from P2824 CSV
    nomenclature_qids = _read_qids_from_csv(ids_dir / f"{_NOMENCLATURE_PID}.csv")

    # Collect object QIDs from all other CSVs
    object_qids: set[str] = set()
    for csv_path in ids_dir.glob("*.csv"):
        if csv_path.stem == _NOMENCLATURE_PID:
            continue
        object_qids.update(_read_qids_from_csv(csv_path))

    objects_dir = wikidata_dir / "objects"
    nomenclature_dir = wikidata_dir / "nomenclature"

    moved_objects = 0
    moved_nomenclature = 0
    skipped = 0

    for entity_file in sorted(entities_dir.glob("Q*.json")):
        qid = entity_file.stem
        if qid in nomenclature_qids:
            dest = nomenclature_dir / entity_file.name
            moved_nomenclature += 1
        elif qid in object_qids:
            dest = objects_dir / entity_file.name
            moved_objects += 1
        else:
            skipped += 1
            continue

        if dry_run:
            logger.info("[dry-run] %s -> %s", entity_file, dest)
        else:
            dest.parent.mkdir(exist_ok=True)
            shutil.move(entity_file, dest)

    logger.info(
        "Migrated %d to objects/, %d to nomenclature/, %d left in entities/",
        moved_objects,
        moved_nomenclature,
        skipped,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Migrate wikidata entities/ layout")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be moved")
    args = parser.parse_args()
    migrate(dry_run=args.dry_run)
