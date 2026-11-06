"""The local and regional layers.

Local is Edenhofer 2024. The regional layer has two variants. `open` is the
Edenhofer 2 kpc map, and the disc layer follows it. `vergely` lays the Vergely
2022 v2 cubes over it, so the cubes' tier binds only that variant.
"""

import logging

import h5py
import numpy as np
from scipy.ndimage import map_coordinates

from space_map_data.dust import nest
from space_map_data.dust.nest import LEVELS
from space_map_data.dust.resample import fill, pixels
from space_map_data.dust.sources import (
    BUILD_DIR,
    NSIDE_EDENHOFER,
    SOURCE_DIR,
    prepare_edenhofer,
)
from space_map_data.utils.paths import SOURCES_DUST_MAPS_DIR

logger = logging.getLogger(__name__)

DEPTH_EDENHOFER = int(np.log2(NSIDE_EDENHOFER))
LOCAL_DIR = BUILD_DIR / "local"
REGIONAL_OPEN_DIR = BUILD_DIR / "regional-open"
REGIONAL_VERGELY_DIR = BUILD_DIR / "regional-vergely"
# The levels each layer is built for. At the others it holds no dust.
LOCAL_LEVELS = LEVELS
REGIONAL_LEVELS = LEVELS[:3]
# Points per voxel axis, set by the size of the smallest source cell in the voxel.
LOCAL_POINTS = {0: 12, 1: 8, 2: 8, 3: 6}
REGIONAL_POINTS = {0: 12, 1: 6, 2: 4}
# The corners of level 2 reach past the Edenhofer map, into the cube.
CUBE_POINTS = {0: 4, 1: 3, 2: 3}
CUBE_DIRECTORY = "explore-lallement-vergely"
CUBE_25 = "explore_cube_density_values_025pc_v2.h5"
CUBE_50 = "explore_cube_density_values_050pc_v2.h5"


def inner_density(r: np.ndarray, column: np.ndarray, edge: np.ndarray, end: float):
    """The density along a ray inside `end`, with the integral `column`.

    It meets `edge`, the first bin of the map, at `end` with zero slope, so the map
    shows no step there. A low column uses a power of r, because the cosine form
    would go below 0.
    """
    cosine = (
        edge + (column - edge * end) * 2.0 / end * np.cos(0.5 * np.pi * r / end) ** 2
    )
    exponent = np.maximum(edge * end / np.maximum(column, 1e-12) - 1.0, 0.0)
    power = edge * np.power(np.clip(r / end, 1e-6, 1.0), exponent)
    return np.where(column < 0.5 * edge * end, power, cosine)


class Spherical:
    """An Edenhofer map with bins [ring, pixel] in mag/pc."""

    def __init__(self, stem: str):
        self.mean = np.load(SOURCE_DIR / f"{stem}.mean.npy", mmap_mode="r")
        self.edges = np.load(SOURCE_DIR / f"{stem}.edges.npy")
        self.inner = np.load(SOURCE_DIR / f"{stem}.inner.npy")

    def density(self, pixel: np.ndarray, r: np.ndarray) -> np.ndarray:
        ring = np.searchsorted(self.edges, r, side="right") - 1
        inside = (ring >= 0) & (ring < len(self.edges) - 1)
        out = np.zeros(len(r), np.float32)
        out[inside] = self.mean[ring[inside], pixel[inside]]
        return out


class LocalSampler:
    def __init__(self):
        self.map = Spherical("e24")
        self.first = np.asarray(self.map.mean[0])

    def __call__(self, x, y, z):
        lon, lat, r = nest.lonlat(x, y, z)
        pixel = pixels(lon, lat, DEPTH_EDENHOFER)
        density = self.map.density(pixel, r)
        near = r < self.map.edges[0]
        density[near] = inner_density(
            r[near],
            self.map.inner[pixel[near]],
            self.first[pixel[near]],
            float(self.map.edges[0]),
        )
        weight = nest.local_weight(r)
        return weight * density, weight


class RegionalOpenSampler:
    def __init__(self):
        self.map = Spherical("e2k")

    def __call__(self, x, y, z):
        lon, lat, r = nest.lonlat(x, y, z)
        pixel = pixels(lon, lat, DEPTH_EDENHOFER)
        weight = (1.0 - nest.local_weight(r)) * nest.regional_weight(r)
        return weight * self.map.density(pixel, r), weight


class Cube:
    """An EXPLORE cube [ix, iy, iz] in mag/pc."""

    def __init__(self, name: str):
        path = SOURCES_DUST_MAPS_DIR / CUBE_DIRECTORY / name
        with h5py.File(path, "r") as handle:
            dataset = handle["explore/cube_datas"]
            self.data = np.asarray(dataset[...], np.float32)
            self.step = float(dataset.attrs["gridstep_values"][0])
            sun = np.asarray(dataset.attrs["sun_position"], np.float64)
        # `sun_position` is (z, y, x) in edge coordinates.
        self.sun = np.array((sun[2] - 0.5, sun[1] - 0.5, sun[0] - 0.5))

    def density(self, x, y, z) -> np.ndarray:
        at = np.stack((x, y, z)) / self.step + self.sun[:, None]
        return map_coordinates(self.data, at, order=1, mode="nearest").astype("f4")


class RegionalVergelySampler:
    def __init__(self):
        self.fine, self.coarse = Cube(CUBE_25), Cube(CUBE_50)

    def __call__(self, x, y, z):
        _, _, r = nest.lonlat(x, y, z)
        first, second = nest.cube_weights(x, y, z)
        outer = 1.0 - nest.local_weight(r)
        first, second = outer * first, outer * (1.0 - first) * second
        value = np.zeros(len(x), np.float32)
        for weight, cube in ((first, self.fine), (second, self.coarse)):
            used = weight > 0.0
            value[used] += weight[used] * cube.density(x[used], y[used], z[used])
        return value, first + second


def build_local(workers: int) -> None:
    prepare_edenhofer()
    sampler = LocalSampler()
    for level in LOCAL_LEVELS:
        reach = (0.0, nest.LOCAL_FADE[1])
        fill(level, LOCAL_DIR, sampler, LOCAL_POINTS[level.index], workers, reach)
        logger.info("local: level %d done", level.index)


def build_regional_open(workers: int) -> None:
    prepare_edenhofer()
    sampler = RegionalOpenSampler()
    reach = (nest.LOCAL_FADE[0], nest.REGIONAL_FADE[1])
    for level in REGIONAL_LEVELS:
        fill(
            level,
            REGIONAL_OPEN_DIR,
            sampler,
            REGIONAL_POINTS[level.index],
            workers,
            reach,
        )
        logger.info("regional open: level %d done", level.index)


def build_regional_vergely(workers: int) -> None:
    sampler = RegionalVergelySampler()
    reach = (nest.LOCAL_FADE[0], 7500.0)
    for level in REGIONAL_LEVELS:
        points = CUBE_POINTS[level.index]
        fill(level, REGIONAL_VERGELY_DIR, sampler, points, workers, reach)
        logger.info("regional vergely: level %d done", level.index)
