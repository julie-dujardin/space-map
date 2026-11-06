"""The model's volumes: an inner box about the Galactic centre, and a coarse outer
box for the halo, the far outer disc and the Magellanic Clouds. A march reads the
finest box that holds a sample, as the dust nest does.

Both are on nest axes. The inner box maps height above the plane through asinh, so
its few slices are thin at the plane, where the young disc and the dust are, and
thick far from it. A voxel holds the mean over its volume, from stratified points.
"""

from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property

import numpy as np

from space_map_data.dust.parallel import forked_map
from space_map_data.galaxy.geometry import R0, Z0

CENTRE = (R0, 0.0, -Z0)


@dataclass(frozen=True)
class Box:
    """A volume about `CENTRE`: half extents (pc), texels (x, y, z) and the asinh
    scale of height (pc), 0 for a linear map."""

    half: tuple[float, float, float]
    size: tuple[int, int, int]
    z_scale: float = 0.0

    @property
    def z_span(self) -> float:
        """asinh(half height / z_scale)."""
        return float(np.arcsinh(self.half[2] / self.z_scale)) if self.z_scale else 1.0

    def height_of(self, w: np.ndarray) -> np.ndarray:
        """Height from the centre (pc) at texture coordinate w in [0, 1]."""
        t = 2.0 * np.asarray(w) - 1.0
        if self.z_scale:
            return self.z_scale * np.sinh(t * self.z_span)
        return t * self.half[2]

    def texture_of_height(self, dz: np.ndarray) -> np.ndarray:
        if self.z_scale:
            return 0.5 + 0.5 * np.arcsinh(dz / self.z_scale) / self.z_span
        return 0.5 + 0.5 * dz / self.half[2]

    def uvw(self, points: np.ndarray) -> np.ndarray:
        """Texture coordinates of points (n, 3), as the shader takes them."""
        d = points - np.array(CENTRE)
        return np.column_stack(
            (
                0.5 + 0.5 * d[:, 0] / self.half[0],
                0.5 + 0.5 * d[:, 1] / self.half[1],
                self.texture_of_height(d[:, 2]),
            )
        )

    def inside(self, points: np.ndarray) -> np.ndarray:
        d = np.abs(points - np.array(CENTRE))
        return np.all(d <= np.array(self.half), axis=1)

    def edges(self, axis: int) -> np.ndarray:
        """Voxel edges along an axis, relative to the centre (pc)."""
        n = self.size[axis]
        if axis == 2:
            return self.height_of(np.arange(n + 1) / n)
        return (np.arange(n + 1) / n * 2.0 - 1.0) * self.half[axis]

    @cached_property
    def heights(self) -> np.ndarray:
        """The physical size of each slice in z (pc)."""
        return np.diff(self.edges(2))

    def halved(self) -> Box:
        nx, ny, nz = self.size
        return Box(self.half, (nx // 2, ny // 2, nz // 2), self.z_scale)


# The inner box holds the disc to R = 24 kpc past the centre, and the dust box's far
# corners. Its slices are 35 pc at the plane on `high`.
INNER_HIGH = Box((24_000.0, 24_000.0, 3_000.0), (512, 512, 32), 150.0)
# The outer box holds the Clouds and the halo to 64 kpc from the centre, at 1 kpc.
OUTER_HIGH = Box((64_000.0, 64_000.0, 64_000.0), (128, 128, 128))
TIERS = {
    "high": {"inner": INNER_HIGH, "outer": OUTER_HIGH},
    "low": {"inner": INNER_HIGH.halved(), "outer": OUTER_HIGH.halved()},
}
POINTS_PER_AXIS = 3


@dataclass(frozen=True)
class _Job:
    box: Box
    sampler: Callable[[np.ndarray], np.ndarray]
    channels: int
    per_axis: int
    seed: int


_job: _Job | None = None


def _slab(ix: int) -> np.ndarray:
    """The mean of the sampler over each voxel of one x slab, shape (ny, nz, c)."""
    job = _job
    assert job is not None
    box, k = job.box, job.per_axis
    rng = np.random.default_rng((job.seed, ix))
    ex, ey, ez = box.edges(0), box.edges(1), box.edges(2)
    ny, nz = box.size[1], box.size[2]
    out = np.zeros((ny, nz, job.channels))
    cells = (np.arange(k) + 0.5) / k
    for iz in range(nz):
        jitter = rng.random((ny, k, k, k, 3)) - 0.5
        ax = ex[ix] + (ex[ix + 1] - ex[ix]) * (
            cells[None, :, None, None] + jitter[..., 0] / k
        )
        ay = ey[:-1, None, None, None] + (ey[1] - ey[0]) * (
            cells[None, None, :, None] + jitter[..., 1] / k
        )
        az = ez[iz] + (ez[iz + 1] - ez[iz]) * (
            cells[None, None, None, :] + jitter[..., 2] / k
        )
        points = np.stack(np.broadcast_arrays(ax, ay, az), axis=-1).reshape(
            -1, 3
        ) + np.array(CENTRE)
        values = job.sampler(points)
        out[:, iz] = values.reshape(ny, k**3, job.channels).mean(axis=1)
    return out


def bake(box: Box, sampler, channels: int, workers: int, seed: int = 0) -> np.ndarray:
    """The voxel means of `sampler(points) -> (n, channels)`, shape (nx, ny, nz, c)."""
    global _job
    _job = _Job(box, sampler, channels, POINTS_PER_AXIS, seed)
    try:
        slabs = forked_map(_slab, range(box.size[0]), workers)
    finally:
        _job = None
    return np.stack(slabs).astype(np.float32)


def block_mean(volume: np.ndarray, box: Box) -> np.ndarray:
    """The next tier down: the mean over 2 x 2 x 2 voxels, by volume, since slices
    differ in height."""
    nx, ny, nz = volume.shape[:3]
    heights = box.heights[None, None, :, None]
    weighted = (volume * heights).reshape(nx // 2, 2, ny // 2, 2, nz // 2, 2, -1)
    total = weighted.sum(axis=(1, 3, 5))
    pairs = box.heights.reshape(nz // 2, 2).sum(axis=1)[None, None, :, None]
    return (total / (4.0 * pairs)).astype(np.float32)
