"""Mean density over each voxel.

A sample at the voxel centre misses structure smaller than the voxel, so a voxel
takes the mean of jittered points inside it. Jitter stops the points from
aliasing against HEALPix pixels and distance bins.

A sampler returns (value, support) at each point. The support is the share that
the layer holds there, and the value is the support times the density. The
shares of the layers sum to 1, so a merge is a sum.
"""

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from astropy import units as u
from astropy.coordinates import Latitude, Longitude
from cdshealpix import nested

from space_map_data.dust import nest
from space_map_data.dust.nest import Level
from space_map_data.dust.parallel import forked_map

logger = logging.getLogger(__name__)

Sampler = Callable[[np.ndarray, np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray]]

POINTS_PER_BLOCK = 2_000_000


def pixels(lon: np.ndarray, lat: np.ndarray, depth: int) -> np.ndarray:
    """Nested HEALPix pixels from Galactic longitude and latitude in radians."""
    found = nested.lonlat_to_healpix(
        Longitude(lon, u.rad), Latitude(lat, u.rad), depth, num_threads=1
    )
    return found.astype(np.int64)


def points_pixels(points: np.ndarray, depth: int) -> np.ndarray:
    """Nested HEALPix pixels of the directions of an (n, 3) array, on Galactic axes."""
    lon, lat, _ = nest.lonlat(*points.T)
    return pixels(lon, lat, depth)


@dataclass(frozen=True)
class Job:
    level: Level
    value: np.ndarray
    support: np.ndarray
    sampler: Sampler
    per_axis: int
    reach: tuple[float, float]
    seed: int


_job: Job | None = None


def stratified(
    centres: np.ndarray, voxel: np.ndarray, per_axis: int, rng: np.random.Generator
) -> np.ndarray:
    """Points of shape (voxels, per_axis ** 3, 3), one in each sub-cell."""
    axis = np.arange(per_axis)
    cells = np.stack(np.meshgrid(axis, axis, axis, indexing="ij"), -1).reshape(-1, 3)
    shape = (len(centres), len(cells), 3)
    jitter = rng.random(shape, dtype=np.float32)
    return centres[:, None, :] + ((cells + jitter) / per_axis - 0.5) * voxel


def _slice(ix: int) -> None:
    job = _job
    assert job is not None
    level, per_axis = job.level, job.per_axis
    rng = np.random.default_rng((job.seed, level.index, ix))
    x = level.centres(0)[ix]
    y, z = level.centres(1), level.centres(2)
    iy, iz = np.meshgrid(
        np.arange(level.shape[1]), np.arange(level.shape[2]), indexing="ij"
    )
    r = np.sqrt(x * x + y[iy] ** 2 + z[iz] ** 2)
    corner = 0.5 * float(np.linalg.norm(level.voxel))
    keep = (r + corner >= job.reach[0]) & (r - corner <= job.reach[1])
    iy, iz = iy[keep], iz[keep]
    block = max(1, POINTS_PER_BLOCK // per_axis**3)
    for start in range(0, len(iy), block):
        jy, jz = iy[start : start + block], iz[start : start + block]
        centres = np.stack((np.full(len(jy), x), y[jy], z[jz]), -1)
        points = stratified(centres, level.voxel, per_axis, rng).reshape(-1, 3)
        value, support = job.sampler(points[:, 0], points[:, 1], points[:, 2])
        count = per_axis**3
        job.value[ix, jy, jz] = value.reshape(-1, count).mean(axis=1)
        job.support[ix, jy, jz] = support.reshape(-1, count).mean(axis=1)


def fill(
    level: Level,
    directory: Path,
    sampler: Sampler,
    per_axis: int,
    workers: int,
    reach: tuple[float, float] = (0.0, np.inf),
    seed: int = 0,
) -> None:
    """Write `l<n>.value.npy` and `l<n>.support.npy` in `directory`.

    A voxel wholly outside the distances in `reach` stays 0.
    """
    global _job
    directory.mkdir(parents=True, exist_ok=True)
    names = [directory / f"l{level.index}.{name}.npy" for name in ("value", "support")]
    temporary = [path.with_suffix(".tmp") for path in names]
    value, support = (
        np.lib.format.open_memmap(path, mode="w+", dtype="f4", shape=level.shape)
        for path in temporary
    )
    _job = Job(level, value, support, sampler, per_axis, reach, seed)
    try:
        forked_map(_slice, range(level.shape[0]), workers)
    finally:
        _job = None
    value.flush()
    support.flush()
    del value, support
    for source, name in zip(temporary, names):
        os.replace(source, name)
