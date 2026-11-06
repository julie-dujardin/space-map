"""Rays through the nest.

The finest level that holds a point serves it. `Stack` reads one field per level,
and `segments` cuts a ray into the parts each level serves.
"""

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from space_map_data.dust.nest import LEVELS, Level


def _slab(origin: np.ndarray, directions: np.ndarray, half: tuple[float, float, float]):
    """Distances along each ray where it enters and leaves a centred box."""
    safe = np.where(np.abs(directions) < 1e-12, 1e-12, directions)
    near = (-np.array(half) - origin) / safe
    far = (np.array(half) - origin) / safe
    enter = np.minimum(near, far).max(axis=1)
    leave = np.maximum(near, far).min(axis=1)
    enter = np.maximum(enter, 0.0)
    return enter, np.maximum(leave, enter)


def segments(
    origin: np.ndarray, directions: np.ndarray
) -> list[tuple[int, np.ndarray, np.ndarray]]:
    """Parts of each ray as (level index, start, stop). A part may be empty."""
    parts = []
    inner: tuple[np.ndarray, np.ndarray] | None = None
    for level in reversed(LEVELS):
        enter, leave = _slab(origin, directions, level.half)
        if inner is None:
            parts.append((level.index, enter, leave))
        else:
            hole_in, hole_out = inner
            empty = hole_out <= hole_in
            first_stop = np.where(empty, leave, hole_in)
            parts.append((level.index, enter, np.minimum(first_stop, leave)))
            parts.append((level.index, np.where(empty, leave, hole_out), leave))
        inner = (enter, leave)
    return parts


def voxel_index(level: Level, shape: tuple[int, ...], points: np.ndarray):
    """The voxel of each point in a grid of the level's box, clipped to the grid."""
    at = (points + np.array(level.half)) / (2 * np.array(level.half)) * np.array(shape)
    at = np.floor(at).astype(np.int32)
    return tuple(np.clip(at[:, axis], 0, shape[axis] - 1) for axis in range(3))


def linear_fetch(grid: np.ndarray, at: np.ndarray) -> np.ndarray:
    """The hardware LINEAR fetch of a grid indexed [x, y, z], with channels last if
    it has any. `at` is (n, 3) texture coordinates, 0 at the low face and 1 at the high
    one. A point outside reads the edge texel. The weights are float32 as on a GPU, and
    the caller decodes the result."""
    size = np.array(grid.shape[:3])
    texel = np.clip(at * size - 0.5, 0, size - 1)
    low = np.minimum(texel.astype(np.int32), size - 2)
    weight = (texel - low).astype(np.float32)
    x, y, z = low.T
    # One weight per point, shaped to broadcast over the channels.
    fx, fy, fz = (
        weight[:, axis].reshape((-1,) + (1,) * (grid.ndim - 3)) for axis in range(3)
    )
    near = (grid[x, y, z] * (1 - fx) + grid[x + 1, y, z] * fx) * (1 - fy) + (
        grid[x, y + 1, z] * (1 - fx) + grid[x + 1, y + 1, z] * fx
    ) * fy
    far = (grid[x, y, z + 1] * (1 - fx) + grid[x + 1, y, z + 1] * fx) * (1 - fy) + (
        grid[x, y + 1, z + 1] * (1 - fx) + grid[x + 1, y + 1, z + 1] * fx
    ) * fy
    return near * (1 - fz) + far * fz


def trilinear(level: Level, grid: np.ndarray, points: np.ndarray) -> np.ndarray:
    """The hardware fetch of a grid that fills the box of `level`."""
    half = np.array(level.half)
    return linear_fetch(grid, (points + half) / (2 * half))


class Stack:
    """One field per level, read at the nearest voxel. A missing level reads 0."""

    def __init__(self, grids: Mapping[int, np.ndarray]):
        self.grids = grids

    def read(self, level_index: int, points: np.ndarray) -> np.ndarray:
        grid = self.grids.get(level_index)
        if grid is None:
            return np.zeros(len(points), np.float32)
        return grid[voxel_index(LEVELS[level_index], grid.shape, points)]


class LinearStack(Stack):
    """Linear filter on linear density: the reference for a filtered fetch."""

    def read(self, level_index: int, points: np.ndarray) -> np.ndarray:
        grid = self.grids.get(level_index)
        if grid is None:
            return np.zeros(len(points), np.float32)
        return trilinear(LEVELS[level_index], grid, points)


class CodeStack(Stack):
    """R8 codes read as a texture does: filter the codes, then decode."""

    def __init__(self, grids: Mapping[int, np.ndarray], encodings: Mapping[int, Any]):
        super().__init__(grids)
        self.encodings = encodings

    def read(self, level_index: int, points: np.ndarray) -> np.ndarray:
        filtered = trilinear(LEVELS[level_index], self.grids[level_index], points)
        return self.encodings[level_index].decode(filtered)


def finest_level(points: np.ndarray, last: int = len(LEVELS) - 1) -> np.ndarray:
    """The index of the finest level up to `last` that holds each point, or -1."""
    found = np.full(len(points), -1, np.int8)
    for level in LEVELS[: last + 1]:
        found[(np.abs(points) <= np.array(level.half)).all(axis=1)] = level.index
    return found


def integrate(
    stacks: Sequence[Stack],
    origin: np.ndarray,
    directions: np.ndarray,
    per_voxel: float = 2.0,
) -> np.ndarray:
    """Integrals along rays of each stack, shape (len(stacks), rays).

    Steps sample the voxels `per_voxel` times along the ray.
    """
    total = np.zeros((len(stacks), len(directions)))
    for index, start, stop in segments(origin, directions):
        length = stop - start
        used = length > 0
        if not used.any():
            continue
        step = float(LEVELS[index].voxel.min()) / per_voxel
        count = int(np.ceil(length.max() / step))
        ds = length[used] / count
        for i in range(count):
            points = origin + directions[used] * (start[used] + (i + 0.5) * ds)[:, None]
            for j, stack in enumerate(stacks):
                total[j, used] += stack.read(index, points) * ds
    return total


def march(
    stack: Stack,
    origin: np.ndarray,
    directions: np.ndarray,
    growth: float,
    first: float,
    voxels_per_step: float | None = None,
    jitter: np.ndarray | None = None,
) -> np.ndarray:
    """Optical depth along rays with steps that grow from the camera.

    Each step samples once, at its middle. With `voxels_per_step`, a sample reads
    the finest level that holds the point and whose voxel is at least the step over
    that number. A point that only a finer level holds reads that level.
    """
    tau = np.zeros(len(directions))
    voxels = np.array([float(level.voxel.min()) for level in LEVELS])
    near, far = 0.0, first
    outer = float(np.linalg.norm(LEVELS[0].half)) + float(np.linalg.norm(origin))
    while near < outer:
        ds = far - near
        offset = 0.5 if jitter is None else jitter[:, None]
        points = origin + directions * (near + offset * ds)
        found = finest_level(points)
        if voxels_per_step is not None:
            limit = (
                int(np.searchsorted(-voxels, -ds / voxels_per_step, side="right")) - 1
            )
            coarse = finest_level(points, max(limit, 0))
            found = np.where(coarse >= 0, coarse, found)
        for level in LEVELS:
            chosen = found == level.index
            if chosen.any():
                tau[chosen] += stack.read(level.index, points[chosen]) * ds
        near, far = far, far * (1.0 + growth)
    return tau
