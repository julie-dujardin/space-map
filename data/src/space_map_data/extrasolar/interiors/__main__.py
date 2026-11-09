"""CLI: python -m space_map_data.extrasolar.interiors

`build` writes the grid tables when they are missing. `region` writes the
Interior rows of one sky region to a directory of your choice, its surface
values to `surface/` and its family masks to `families/` below it, with their
counts, as the export would write them to its scratch.
"""

import argparse
import json
import logging.config
import tomllib
from pathlib import Path

from space_map_data.extrasolar import surface
from space_map_data.extrasolar.interiors import grid, table
from space_map_data.extrasolar.registry import Registry
from space_map_data.utils.paths import DATA_DIR, REGISTRY_ROOT


def cli() -> None:
    parser = argparse.ArgumentParser(description="Stellar interiors")
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("build", help="Write the grid tables")
    region = actions.add_parser("region", help="Write the rows of one region")
    region.add_argument("region", type=int)
    region.add_argument("--out", type=Path, required=True)
    region.add_argument("--root", type=Path, default=REGISTRY_ROOT)
    args = parser.parse_args()
    with open(DATA_DIR / "logging.toml", "rb") as f:
        logging.config.dictConfig(tomllib.load(f))

    tables_dir = grid.ready(grid.TRACKS_DIR, grid.TABLES_ROOT)
    if args.action == "build":
        return
    with Registry(args.root).reader() as registry:
        surface_out = args.out / surface.SCRATCH
        families_out = args.out / table.FAMILIES_SCRATCH
        for directory in (surface_out, families_out):
            directory.mkdir(parents=True, exist_ok=True)
        job = table.RegionJob(
            registry,
            args.region,
            args.out,
            surface_out,
            families_out,
            table.curated(registry),
            tables_dir,
        )
        counts = table.region_rows(job)
    print(json.dumps(dict(sorted(counts.items())), indent=1))


if __name__ == "__main__":
    cli()
