"""CLI entry point for: space-map-glow"""

import argparse
import logging
import logging.config
import time
import tomllib
from pathlib import Path

from space_map_data.glow import build, gates
from space_map_data.utils.paths import DATA_DIR

STEPS = {
    "sun-map": build.build_sun_map,
    "duplicates": build.build_duplicates,
    "deposit": build.build_deposit,
    "encode": lambda directory, _workers: build.build_encoded(directory),
    "gate-light": gates.light_gate,
    "gate-sun": gates.sun_gate,
    "gate-cut": gates.cut_gate,
    "gate-tiers": gates.tier_gate,
}


def cli():
    parser = argparse.ArgumentParser(description="Build the catalogue light grid")
    parser.add_argument("steps", nargs="+", choices=STEPS)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--build", type=Path, default=build.BUILD_DIR)
    args = parser.parse_args()
    with open(DATA_DIR / "logging.toml", "rb") as f:
        logging.config.dictConfig(tomllib.load(f))
    logger = logging.getLogger("space_map_data.glow")
    args.build.mkdir(parents=True, exist_ok=True)
    for step in args.steps:
        started = time.monotonic()
        STEPS[step](args.build, args.workers)
        logger.info("%s: %.0f s", step, time.monotonic() - started)


if __name__ == "__main__":
    cli()
