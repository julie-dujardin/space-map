"""CLI entry point for: space-map-emission"""

import argparse
import logging
import logging.config
import time
import tomllib
from pathlib import Path

from space_map_data.emission import build, gates
from space_map_data.utils.paths import DATA_DIR

STEPS = {
    "local": build.build_local,
    "regions": build.build_regions,
    "sun": build.build_sun,
    "scale": build.build_scale,
    "scatter": build.build_scatter,
    "shield": build.build_shield,
    "encode": build.build_encoded,
    "gate-halpha": gates.halpha_gate,
    "gate-dimming": gates.dimming_gate,
    "gate-wise": gates.wise_gate,
    "gate-scatter": gates.scatter_gate,
    "gate-isotropy": gates.isotropy_gate,
    "gate-sun": gates.sun_gate,
    "gate-tiers": gates.tier_gate,
}


def cli():
    parser = argparse.ArgumentParser(
        description="Build H-alpha and scattered starlight for the 3D Milky Way"
    )
    parser.add_argument("steps", nargs="+", choices=list(STEPS))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--build", type=Path, default=build.BUILD_DIR)
    args = parser.parse_args()
    with open(DATA_DIR / "logging.toml", "rb") as f:
        logging.config.dictConfig(tomllib.load(f))
    logger = logging.getLogger("space_map_data.emission")
    args.build.mkdir(parents=True, exist_ok=True)
    for step in args.steps:
        started = time.monotonic()
        STEPS[step](args.build, args.workers)
        logger.info("%s: %.0f s", step, time.monotonic() - started)


if __name__ == "__main__":
    cli()
