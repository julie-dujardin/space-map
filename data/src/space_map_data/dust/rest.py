"""The rest layer: a flagged model for the dust past the observed maps.

It copies the method of Drimmel et al. 2003. Each sightline holds the Planck total
minus the observed column, clipped at zero, along an exponential disc. A later
phase replaces this layer.
"""

import json
import logging

import numpy as np
from astropy import units as u
from astropy.coordinates import Latitude, Longitude
from cdshealpix import nested

from space_map_data.dust import nest
from space_map_data.dust.march import Stack, integrate
from space_map_data.dust.merge import build_observed, merged_dir
from space_map_data.dust.nest import LEVELS
from space_map_data.dust.parallel import forked_map
from space_map_data.dust.resample import fill
from space_map_data.dust.sky import SKY_DIR
from space_map_data.dust.sources import BUILD_DIR, atomic_npy

logger = logging.getLogger(__name__)

SHAPE_DIR = BUILD_DIR / "rest-shape"
SHAPE_POINTS = 4
RAY_DEPTH = 8
SIGHTLINE_DEPTH = 7
# Drimmel & Spergel 2001, Table 1 and section 3, with the Sun at R = 8 kpc.
R_SUN = 8000.0
Z_SUN = 15.0
SCALE_LENGTH = 2260.0
SCALE_HEIGHT = 134.4
FLARE = 14.8e-3
FLARE_RADIUS = 4400.0
# A sightline may hold up to this many times the Planck total scaled to the whole
# shape. Off the plane the shape has no room, and the remainder there is noise.
MAX_OVER_PLANCK_SCALE = 3.0
RAY_CHUNK = 20000


def disc_shape(x, y, z) -> np.ndarray:
    """The disc density, 1 at the solar circle on the plane."""
    radius = np.hypot(x - R_SUN, y)
    height = SCALE_HEIGHT + FLARE * np.maximum(radius - FLARE_RADIUS, 0.0)
    inner = 0.5 * R_SUN
    radial = np.exp(-(np.maximum(radius, inner) - R_SUN) / SCALE_LENGTH)
    hole = np.exp(-(((np.minimum(radius - inner, 0.0)) / (0.25 * R_SUN)) ** 2))
    return radial * hole / np.cosh((z + Z_SUN) / height) ** 2


def _shape_sampler(x, y, z):
    return disc_shape(x, y, z), np.ones(len(x), np.float32)


def build_shape(workers: int) -> None:
    for level in LEVELS:
        fill(level, SHAPE_DIR, _shape_sampler, SHAPE_POINTS, workers)


def _stack(directory, suffix: str) -> Stack:
    return Stack(
        {
            level.index: np.load(
                directory / f"l{level.index}.{suffix}.npy", mmap_mode="r"
            )
            for level in LEVELS
        }
    )


def _columns(job: tuple[str, np.ndarray]) -> np.ndarray:
    variant, directions = job
    directory = merged_dir(variant)
    stacks = (
        _stack(directory, "observed"),
        _stack(directory, "rest_weight"),
        _stack(SHAPE_DIR, "value"),
    )
    return integrate(stacks, np.zeros(3), directions)


def sky_columns(variant: str, workers: int) -> np.ndarray:
    """Columns on Nside 256 rays: observed, shape in the rest share, whole shape."""
    pixels_all = np.arange(12 * 4**RAY_DEPTH, dtype=np.uint64)
    lon, lat = nested.healpix_to_lonlat(pixels_all, RAY_DEPTH)
    directions = nest.directions(lon.to_value(u.rad), lat.to_value(u.rad))
    jobs = [
        (variant, directions[start : start + RAY_CHUNK])
        for start in range(0, len(directions), RAY_CHUNK)
    ]
    return np.concatenate(forked_map(_columns, jobs, workers), axis=1)


def sightline_scale(
    total: np.ndarray, seen: np.ndarray, room: np.ndarray, whole: np.ndarray
) -> np.ndarray:
    """The density at the solar circle that holds the remainder of each sightline."""
    remainder = np.maximum(total - seen, 0.0)
    wanted = np.divide(remainder, room, out=np.zeros_like(room), where=room > 0)
    limit = MAX_OVER_PLANCK_SCALE * total / whole
    return np.minimum(wanted, limit)


def build_rest(variant: str, workers: int) -> None:
    build_observed(variant)
    directory = merged_dir(variant)
    for level in LEVELS:
        share = np.load(directory / f"l{level.index}.rest_share.npy")
        shape = np.load(SHAPE_DIR / f"l{level.index}.value.npy")
        atomic_npy(directory / f"l{level.index}.rest_weight.npy", share * shape)
    observed, weighted, whole = sky_columns(variant, workers)
    atomic_npy(directory / "sky.observed.npy", observed.astype("f4"))

    per_sightline = 4 ** (RAY_DEPTH - SIGHTLINE_DEPTH)
    total = np.load(SKY_DIR / "planck.total.npy")
    total = total.reshape(-1, per_sightline).mean(axis=1)
    seen = observed.reshape(-1, per_sightline).mean(axis=1)
    room = weighted.reshape(-1, per_sightline).mean(axis=1)
    whole = whole.reshape(-1, per_sightline).mean(axis=1)
    scale = sightline_scale(total, seen, room, whole)
    atomic_npy(directory / "sky.rest_scale.npy", scale.astype("f4"))
    remainder = np.maximum(total - seen, 0.0)
    placed = scale * room
    report = {
        "remainder_mag_mean": float(remainder.mean()),
        "placed_mag_mean": float(placed.mean()),
        "unplaced_share": float(1.0 - placed.sum() / max(remainder.sum(), 1e-30)),
        "sightlines": len(scale),
    }
    (directory / "rest.json").write_text(json.dumps(report, indent=1))
    logger.info("rest %s: %s", variant, report)

    for level in LEVELS:
        weight = np.load(directory / f"l{level.index}.rest_weight.npy")
        atomic_npy(
            directory / f"l{level.index}.rest.npy",
            _sky_scale(level, scale) * weight,
        )


def _sky_scale(level, scale: np.ndarray) -> np.ndarray:
    """The sightline scale at each voxel centre, bilinear on the sky."""
    out = np.zeros(level.shape, np.float32)
    y, z = np.meshgrid(level.centres(1), level.centres(2), indexing="ij")
    for ix, x in enumerate(level.centres(0)):
        lon, lat, _ = nest.lonlat(np.full(y.shape, x), y, z)
        keep = np.abs(lat) < np.pi / 2
        corners, weights = nested.bilinear_interpolation(
            Longitude(lon[keep], u.rad), Latitude(lat[keep], u.rad), SIGHTLINE_DEPTH
        )
        out[ix][keep] = (scale[corners.astype(np.int64)] * weights).sum(axis=1)
    return out
