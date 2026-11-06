"""The layout of the light grid: cells of the sky seen from the Sun, in shells.

A texel of the grid is one octahedral cell of the sky, as in the dust sky map, with a
ring of one texel past the edge of the square. A shell is even in log(1 + r / scale).
So a voxel spans the same solid angle at every distance, and it grows along the line
of sight as a star's distance error does.
"""

from dataclasses import dataclass
from functools import cached_property

import numpy as np

from space_map_data.glow.sky_map import map_uv, uv_directions

# Points per axis in a texel for its solid angle.
ANGLE_POINTS = 16


@dataclass(frozen=True)
class SkyGrid:
    size: int
    shells: int
    scale: float
    reach: float

    @property
    def shape(self) -> tuple[int, int, int]:
        """Index order [shell, row, column]: z, y, x of the texture."""
        return self.shells, self.size, self.size

    @property
    def span(self) -> float:
        return float(np.log1p(self.reach / self.scale))

    def edges(self) -> np.ndarray:
        """The shell edges in pc."""
        return self.scale * np.expm1(
            np.arange(self.shells + 1) / self.shells * self.span
        )

    def shell_of(self, r: np.ndarray) -> np.ndarray:
        at = np.log1p(r / self.scale) / self.span * self.shells
        return np.minimum(at.astype(np.int32), self.shells - 1)

    def cell_of(self, d: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """The row and column of each unit direction."""
        u, v = map_uv(d, self.size)
        limit = self.size - 2
        return (
            np.clip((v * self.size).astype(np.int32), 1, limit),
            np.clip((u * self.size).astype(np.int32), 1, limit),
        )

    def voxel_of(self, points: np.ndarray) -> np.ndarray:
        """The flat index of each point, from the Sun."""
        r = np.linalg.norm(points, axis=1)
        d = np.zeros_like(points)
        d[:, 2] = 1.0
        safe = r > 1e-9
        d[safe] = points[safe] / r[safe, None]
        row, column = self.cell_of(d)
        return (
            self.shell_of(r).astype(np.int64) * self.size + row
        ) * self.size + column

    @cached_property
    def angles(self) -> np.ndarray:
        """The solid angle of each cell in sr, 0 in the ring, shape (size, size)."""
        n = self.size
        fine = (np.arange(ANGLE_POINTS * n) + 0.5) / (ANGLE_POINTS * n)
        # The map is not equal-area, so a cell needs its own solid angle. A face patch
        # spans it in proportion to |p|^-3, and the weights sum to the sphere.
        out = np.zeros((n, n))
        inner = (fine > 1 / n) & (fine < 1 - 1 / n)
        fine = fine[inner]
        u, v = np.meshgrid(fine, fine, indexing="xy")
        qx = (u - 1 / n) * n / (n - 2) * 2 - 1
        qy = (v - 1 / n) * n / (n - 2) * 2 - 1
        h = 1 - np.abs(qx) - np.abs(qy)
        # The lower half mirrors the upper one, so it takes the same weight.
        px, py = np.abs(qx), np.abs(qy)
        under = h < 0
        px, py = np.where(under, 1 - py, px), np.where(under, 1 - px, py)
        norm = px * px + py * py + (1 - px - py) ** 2
        weight = norm**-1.5
        row = (v.ravel() * n).astype(np.int32)
        column = (u.ravel() * n).astype(np.int32)
        np.add.at(out, (row, column), weight.ravel())
        return out / out.sum() * 4 * np.pi

    def volumes(self) -> np.ndarray:
        """The volume of each voxel in pc^3, 0 in the ring, as `shape`."""
        cubes = self.edges() ** 3 / 3
        return np.diff(cubes)[:, None, None] * self.angles

    def ring_sources(self) -> np.ndarray:
        """For each ring texel, the (row, column) of the cell that holds its ray:
        shape (n, 4) with ring row, ring column, cell row, cell column."""
        n = self.size
        rows, columns = np.indices((n, n))
        ring = (rows == 0) | (rows == n - 1) | (columns == 0) | (columns == n - 1)
        r, c = rows[ring], columns[ring]
        d = uv_directions((c + 0.5) / n, (r + 0.5) / n, n)
        row, column = self.cell_of(d)
        return np.column_stack((r, c, row, column))

    def fill_ring(self, volume: np.ndarray) -> None:
        """Copy the cells to the ring, in place. `volume` starts [shell, row, column]."""
        pairs = self.ring_sources()
        volume[:, pairs[:, 0], pairs[:, 1]] = volume[:, pairs[:, 2], pairs[:, 3]]
