"""Migrate wikidata entities/ into entities/, referenced/, and units/.

One-shot migration: scans the flat entities/ directory and moves referenced
entity and unit files into their own subdirectories.

Usage:
    python -m space_map_data.download.providers.wikidata.migrate_entity_dirs
"""

import json
import logging
import shutil
from pathlib import Path

from space_map_data.download.providers.wikidata.downloader import _REFERENCED_PROPERTIES
from space_map_data.utils.paths import DOWNLOAD_DIR

logger = logging.getLogger(__name__)

WIKIDATA_DIR = DOWNLOAD_DIR / "wikidata"


def _collect_secondary_qids(entities_dir: Path) -> tuple[set[str], set[str]]:
    """Return (referenced_qids, unit_qids) found in root entity claims."""
    referenced: set[str] = set()
    units: set[str] = set()

    for entity_file in entities_dir.glob("Q*.json"):
        try:
            entity = json.loads(entity_file.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        claims = entity.get("claims", {})

        for prop in _REFERENCED_PROPERTIES:
            for stmt in claims.get(prop, []):
                dv = stmt.get("mainsnak", {}).get("datavalue", {}).get("value", {})
                if isinstance(dv, dict) and "id" in dv:
                    referenced.add(dv["id"])

        for prop_stmts in claims.values():
            for stmt in prop_stmts:
                dv = stmt.get("mainsnak", {}).get("datavalue", {}).get("value", {})
                if isinstance(dv, dict) and "unit" in dv:
                    unit = dv["unit"]
                    if isinstance(unit, str) and "wikidata.org/entity/Q" in unit:
                        units.add(unit.rsplit("/", 1)[-1])

    return referenced, units


def migrate() -> None:
    entities_dir = WIKIDATA_DIR / "entities"
    if not entities_dir.exists():
        logger.info("No entities/ directory found, nothing to migrate")
        return

    referenced_dir = WIKIDATA_DIR / "referenced"
    units_dir = WIKIDATA_DIR / "units"

    if referenced_dir.exists() or units_dir.exists():
        logger.info("referenced/ or units/ already exists, skipping migration")
        return

    referenced_qids, unit_qids = _collect_secondary_qids(entities_dir)
    all_qids = {f.stem for f in entities_dir.glob("Q*.json")}

    # Units that are also referenced as entities go to referenced/
    to_referenced = referenced_qids & all_qids
    to_units = (unit_qids - referenced_qids) & all_qids

    if not to_referenced and not to_units:
        logger.info("No referenced or unit entities to migrate")
        return

    referenced_dir.mkdir(exist_ok=True)
    units_dir.mkdir(exist_ok=True)

    moved = 0
    for qid in sorted(to_referenced):
        src = entities_dir / f"{qid}.json"
        if src.exists():
            shutil.move(src, referenced_dir / f"{qid}.json")
            moved += 1

    for qid in sorted(to_units):
        src = entities_dir / f"{qid}.json"
        if src.exists():
            shutil.move(src, units_dir / f"{qid}.json")
            moved += 1

    remaining = len(list(entities_dir.glob("Q*.json")))
    logger.info(
        "Migrated %d files: %d to referenced/, %d to units/ (%d remain in entities/)",
        moved,
        len(to_referenced),
        len(to_units),
        remaining,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    migrate()
