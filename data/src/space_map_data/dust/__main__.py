"""CLI entry point for: space-map-dust"""

import argparse
import logging
import logging.config
import time
import tomllib

from space_map_data.dust import (
    VARIANTS,
    disc,
    encode,
    gates,
    layers,
    merge,
    rest,
    sky,
)
from space_map_data.utils.paths import DATA_DIR


def _reduce(_workers: int) -> None:
    disc.reduce_decaps()
    disc.reduce_bayestar()


def _sky(_workers: int) -> None:
    sky.prepare_planck()
    sky.prepare_tge()


def _calibrate(_workers: int) -> None:
    disc.calibrate()


STEPS = {
    "local": layers.build_local,
    "regional-open": layers.build_regional_open,
    "regional-vergely": layers.build_regional_vergely,
    "reduce-disc": _reduce,
    "sky": _sky,
    "calibrate": _calibrate,
    "disc": disc.build_disc,
    "rest-shape": rest.build_shape,
}
# A step of this table runs once for each variant.
VARIANT_STEPS = {
    "rest": rest.build_rest,
    "merge": lambda variant, _workers: merge.build_density(variant),
    "encode": lambda variant, workers: encode.build_encoded(
        variant, encode.FLOORS, workers
    ),
    "gate-sky": lambda variant, workers: gates.write_gate(
        variant, "sky", gates.sky_gate(variant, workers)
    ),
    "gate-tiers": lambda variant, workers: gates.write_gate(
        variant, "tiers", gates.tier_gate(variant, workers)
    ),
    "gate-bubble": lambda variant, workers: gates.write_gate(
        variant, "bubble", gates.bubble_gate(variant, workers)
    ),
    "gate-seams": lambda variant, workers: gates.write_gate(
        variant, "seams", gates.seam_gate(variant, workers)
    ),
}


def cli():
    parser = argparse.ArgumentParser(description="Build the 3D dust nest")
    parser.add_argument("steps", nargs="+", choices=(*STEPS, *VARIANT_STEPS))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--variant", choices=VARIANTS, action="append")
    args = parser.parse_args()
    with open(DATA_DIR / "logging.toml", "rb") as f:
        logging.config.dictConfig(tomllib.load(f))
    logger = logging.getLogger("space_map_data.dust")
    variants = args.variant or VARIANTS
    for step in args.steps:
        started = time.monotonic()
        if step in STEPS:
            STEPS[step](args.workers)
        else:
            for variant in variants:
                VARIANT_STEPS[step](variant, args.workers)
        logger.info("%s: %.0f s", step, time.monotonic() - started)


if __name__ == "__main__":
    cli()
