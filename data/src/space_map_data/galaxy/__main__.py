"""CLI entry point for: space-map-galaxy"""

import argparse
import logging
import logging.config
import time
import tomllib
from pathlib import Path

from space_map_data.galaxy import build, gates, geometry, residual
from space_map_data.glow import build as glow_build
from space_map_data.utils.paths import DATA_DIR

STEPS = {
    "column": build.build_column,
    "calibrate": build.build_calibration,
    "residual": build.build_residual,
    "encode": build.build_encoded,
    "gate-galaxy": gates.galaxy_gate,
    "gate-excess": gates.excess_gate,
}
# These steps take workers.
PARALLEL = {"bake": build.build_bake, "gate-forms": gates.form_gate}


def cli():
    parser = argparse.ArgumentParser(description="Build the model light of the Galaxy")
    parser.add_argument("steps", nargs="+", choices=(*STEPS, *PARALLEL))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--build", type=Path, default=build.BUILD_DIR)
    parser.add_argument("--glow", type=Path, default=glow_build.BUILD_DIR)
    parser.add_argument(
        "--far-side",
        type=float,
        default=geometry.FAR_SIDE_ARMS,
        help="arm contrast past the Galactic centre; another value wants its own --build",
    )
    parser.add_argument(
        "--fade",
        type=float,
        nargs=2,
        default=None,
        metavar=("START_PC", "END_PC"),
        help="fade the catalogue's weight to 0 over these distances from the Sun",
    )
    parser.add_argument(
        "--no-fade", action="store_true", help="keep the catalogue at 1"
    )
    args = parser.parse_args()
    if args.fade is not None:
        residual.CATALOGUE_FADE_PC = (args.fade[0], args.fade[1])
    if args.no_fade:
        residual.CATALOGUE_FADE_PC = None
    with open(DATA_DIR / "logging.toml", "rb") as f:
        logging.config.dictConfig(tomllib.load(f))
    logger = logging.getLogger("space_map_data.galaxy")
    args.build.mkdir(parents=True, exist_ok=True)
    for step in args.steps:
        started = time.monotonic()
        if step in PARALLEL:
            PARALLEL[step](args.build, args.glow, args.far_side, args.workers)
        else:
            STEPS[step](args.build, args.glow, args.far_side)
        logger.info("%s: %.0f s", step, time.monotonic() - started)


if __name__ == "__main__":
    cli()
