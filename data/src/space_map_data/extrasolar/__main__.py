"""CLI for the extrasolar registry: python -m space_map_data.extrasolar"""

import argparse
import logging.config
import sys
import tomllib
from pathlib import Path

from space_map_data.extrasolar.registry import Registry
from space_map_data.utils.paths import DATA_DIR, REGISTRY_BACKUP_DIR, REGISTRY_ROOT


def _status(registry: Registry) -> None:
    if not registry.manifest:
        print(f"no registry in {registry.root}")
        return
    print(f"registry {registry.root}, minting host {registry.manifest['host']}")
    for entry in registry.ingests:
        counts = " · ".join(f"{k} {v:,}" for k, v in entry["counts"].items())
        review = ""
        if entry["counts"]["merged"]:
            review = (
                f", reviewed {entry['reviewed']}"
                if entry["reviewed"]
                else ", UNREVIEWED"
            )
        print(f"{entry['ingest']:>4} {entry['date'][:19]} {counts}{review}")


def cli() -> None:
    parser = argparse.ArgumentParser(description="The extrasolar ID registry")
    parser.add_argument("--root", type=Path, default=REGISTRY_ROOT)
    parser.add_argument("--backup-root", type=Path, default=REGISTRY_BACKUP_DIR)
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("status", help="List the ingests and their counts")
    report = actions.add_parser("report", help="Print the report of an ingest")
    report.add_argument("ingest", type=int)
    review = actions.add_parser(
        "review", help="Mark the merges of an ingest as checked by hand"
    )
    review.add_argument("ingest", type=int)
    actions.add_parser("backup", help="Copy the segments the backup lacks")
    args = parser.parse_args()

    with open(DATA_DIR / "logging.toml", "rb") as f:
        logging.config.dictConfig(tomllib.load(f))
    registry = Registry(args.root)
    if args.action == "status":
        _status(registry)
    elif args.action == "report":
        sys.stdout.write(registry.report(args.ingest))
    elif args.action == "review":
        with registry.writer():
            registry.mark_reviewed(args.ingest)
            registry.backup(args.backup_root)
        print(f"merges of ingest {args.ingest} marked as reviewed")
    elif args.action == "backup":
        with registry.writer():
            registry.backup(args.backup_root)


if __name__ == "__main__":
    cli()
