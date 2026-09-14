"""Rebuild collection indexes from the products already on disk.

Each run writes its catalog only after its last product, so a run that is
interrupted leaves finished products no index mentions, and the export reads
the index. Recovering them here costs seconds where reprocessing costs hours.
"""

import argparse
import json
import logging
from pathlib import Path

from .pipeline import write_json
from .releases import refresh_catalog

logger = logging.getLogger(__name__)


def rebuild(directory: Path, collection: str) -> tuple[int, int]:
    """Add every built product the collection's index is missing."""
    path = directory / collection / "catalog.json"
    catalog: dict = (
        json.loads(path.read_text())
        if path.exists()
        else {"schema_version": 1, "panoramas": []}
    )
    entries: list[dict] = list(catalog.get("panoramas", []))
    before = len(entries)
    known = {entry["id"] for entry in entries}
    for meta_path in sorted((directory / collection).glob("*/metadata.json")):
        metadata = json.loads(meta_path.read_text())
        if metadata["id"] in known:
            continue
        known.add(metadata["id"])
        entry = {
            "id": metadata["id"],
            "sol": metadata.get("sol"),
            "metadata": str(meta_path.relative_to(directory)),
        }
        if metadata.get("preview"):
            entry["preview"] = str(
                (meta_path.parent / metadata["preview"]).relative_to(directory)
            )
        entries.append(entry)
    added = len(entries) - before
    catalog["panoramas"] = entries
    write_json(path, catalog)
    # Fills mission, position, coverage and the ready flags from each product,
    # so a recovered entry is indistinguishable from one the run wrote.
    refresh_catalog(directory, collection)
    return added, len(entries)


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--collections", nargs="+")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    names = args.collections or sorted(
        entry.name for entry in args.directory.iterdir() if entry.is_dir()
    )
    total = 0
    for collection in names:
        if not (args.directory / collection).is_dir():
            continue
        added, size = rebuild(args.directory, collection)
        total += added
        if added:
            logger.info("%s: recovered %s entries, now %s", collection, added, size)
    print(f"Recovered {total} catalog entries")


if __name__ == "__main__":
    cli()
