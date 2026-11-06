"""Sum the layers of a variant, per level."""

import json
import logging
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from cdshealpix import nested

from space_map_data.dust import nest
from space_map_data.dust.disc import DISC_DIR, DISC_LEVELS
from space_map_data.dust.layers import (
    LOCAL_DIR,
    LOCAL_LEVELS,
    REGIONAL_LEVELS,
    REGIONAL_OPEN_DIR,
    REGIONAL_VERGELY_DIR,
)
from space_map_data.dust.march import Stack, integrate
from space_map_data.dust.nest import LEVELS, Level
from space_map_data.dust.sources import BUILD_DIR, atomic_npy

logger = logging.getLogger(__name__)

SHARE_DEPTH = 5


def merged_dir(variant: str):
    return BUILD_DIR / "merged" / variant


Fields = tuple[np.ndarray, np.ndarray]


def layer_fields(directory: Path, built: Sequence[Level], level: Level) -> Fields:
    """The value and share of a layer at a level.

    A level that the layer is not built for holds none of it. A missing file of a
    built level raises, so an unbuilt layer is not read as a level with no dust.
    """
    if level not in built:
        shape = level.shape
        return np.zeros(shape, "f4"), np.zeros(shape, "f4")
    return (
        np.load(directory / f"l{level.index}.value.npy"),
        np.load(directory / f"l{level.index}.support.npy"),
    )


def combine(
    local: Fields, regional: Fields, disc: Fields, cube: Fields | None = None
) -> Fields:
    """The density of the observed layers and the share left for the rest layer.

    The cubes of `vergely` replace the regional and disc layers in the share that
    they hold.
    """
    local_value, local_share = local
    regional_value, regional_share = regional
    disc_value, disc_share = disc
    if cube is None:
        value = local_value + regional_value + disc_value
        share = local_share + regional_share + disc_share
    else:
        cube_value, cube_share = cube
        over = np.divide(
            cube_share,
            1.0 - local_share,
            out=np.zeros_like(cube_share),
            where=local_share < 1.0,
        )
        over = np.clip(over, 0.0, 1.0)
        value = local_value + cube_value + (1.0 - over) * (regional_value + disc_value)
        share = local_share + cube_share + (1.0 - over) * (regional_share + disc_share)
    return value, np.clip(1.0 - share, 0.0, 1.0)


def observed(variant: str, index: int) -> Fields:
    """The density of the observed layers and the share left for the rest layer."""
    level = LEVELS[index]
    return combine(
        layer_fields(LOCAL_DIR, LOCAL_LEVELS, level),
        layer_fields(REGIONAL_OPEN_DIR, REGIONAL_LEVELS, level),
        layer_fields(DISC_DIR, DISC_LEVELS, level),
        layer_fields(REGIONAL_VERGELY_DIR, REGIONAL_LEVELS, level)
        if variant == "vergely"
        else None,
    )


def build_observed(variant: str) -> None:
    directory = merged_dir(variant)
    for level in LEVELS:
        value, rest_share = observed(variant, level.index)
        atomic_npy(directory / f"l{level.index}.observed.npy", value)
        atomic_npy(directory / f"l{level.index}.rest_share.npy", rest_share)


def build_density(variant: str) -> None:
    """Write `l<n>.density.npy`, the observed layers plus the rest layer."""
    directory = merged_dir(variant)
    for level in LEVELS:
        observed_part = np.load(directory / f"l{level.index}.observed.npy")
        rest = np.load(directory / f"l{level.index}.rest.npy")
        atomic_npy(directory / f"l{level.index}.density.npy", observed_part + rest)
        logger.info("merge %s: level %d done", variant, level.index)
    (directory / "rest_share.json").write_text(
        json.dumps(_rest_shares(variant), indent=1)
    )


def _rest_shares(variant: str) -> dict[str, float]:
    """The rest layer's share of the Sun-view column in the part each level serves."""
    directory = merged_dir(variant)
    lon, lat = nested.healpix_to_lonlat(
        np.arange(12 * 4**SHARE_DEPTH, dtype=np.uint64), SHARE_DEPTH
    )
    directions = nest.directions(lon.to_value("rad"), lat.to_value("rad"))
    shares = {}
    for level in LEVELS:
        grids = [
            np.load(directory / f"l{level.index}.{name}.npy", mmap_mode="r")
            for name in ("rest", "density")
        ]
        rest, total = integrate(
            [Stack({level.index: grid}) for grid in grids], np.zeros(3), directions
        )
        shares[str(level.index)] = round(float(rest.sum() / total.sum()), 4)
    return shares
