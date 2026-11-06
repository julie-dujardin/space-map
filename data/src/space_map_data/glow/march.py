"""Rays through the dust and the light, in NumPy, for the gates.

A sample reads what a shader reads: the column so far gives the cut, the cut gives the
light, and the light takes the column in each channel. Steps are even in
log(1 + s / 10 pc), and a sample sits at the middle of its step.
"""

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from space_map_data.dust.march import linear_fetch
from space_map_data.dust.parallel import forked_stream
from space_map_data.glow import encode, form, light, sky_map
from space_map_data.glow.grid import SkyGrid

# Flux in the frame of the grid is at 10 pc, so a surface brightness per sr takes
# (10 pc)^2.
AT_TEN_PC = 100.0
STEPS = 384

Reader = Callable[[np.ndarray, np.ndarray], np.ndarray]


@dataclass(frozen=True)
class View:
    origin: np.ndarray
    limit: float
    end: float = 500_000.0


# Forked workers read these.
_reader: Reader | None = None
_nest: sky_map.Nest | None = None
_view: View | None = None
_rays: np.ndarray | None = None
_steps = STEPS


class Textures:
    """The two textures of a tier, read with LINEAR as a shader reads them."""

    def __init__(
        self, grid: SkyGrid, bits: np.ndarray, scale: float, table: form.Table
    ):
        self.grid = grid
        self.scale = scale
        self.table = table
        # Stored [shell, row, column, value]; a fetch takes [x, y, z].
        self.volume = encode.bits_to_values(bits).transpose(2, 1, 0, 3)

    def filtered(self, points: np.ndarray) -> np.ndarray:
        """The eight values at each point, the light in flux density per pc^3."""
        grid = self.grid
        r = np.linalg.norm(points, axis=1)
        d = points / np.maximum(r, 1e-9)[:, None]
        u, v = sky_map.map_uv(d, grid.size)
        w = np.log1p(r / grid.scale) / grid.span
        out = linear_fetch(self.volume, np.stack((u, v, w), axis=1)).astype(np.float64)
        out[:, : form.VALUES - 1] /= self.scale
        out[r > grid.reach, : form.VALUES - 1] = 0
        return out

    def read(self, points: np.ndarray, m_cut: np.ndarray) -> np.ndarray:
        return form.read_values(self.filtered(points), m_cut, self.table)


def march(
    reader: Reader, nest: sky_map.Nest, view: View, rays: np.ndarray, steps: int = STEPS
) -> np.ndarray:
    """Surface brightness toward each unit direction, in flux of M = 0 at 10 pc per
    sr per channel, as seen through the dust, shape (n, 3)."""
    origin = view.origin
    span = np.log1p(view.end / 10.0)
    lnq = span / steps
    total = np.zeros((len(rays), 3))
    column = np.zeros(len(rays))
    start = 0.0
    for i in range(steps):
        stop = 10.0 * np.expm1((i + 1) * lnq)
        mid = 10.0 * np.expm1((i + 0.5) * lnq)
        ds = stop - start
        points = origin + rays * mid
        half = sky_map.density(nest, points).astype(np.float64) * ds / 2
        column += half
        cut = view.limit - 5 * np.log10(mid / 10) - light.K_G * column
        j = reader(points, cut)
        transmission = 10.0 ** (-0.4 * light.K_RGB[None, :] * column[:, None])
        total += j * transmission * ds * AT_TEN_PC
        column += half
        start = stop
    return total


def _rays_job(chunk: slice) -> np.ndarray:
    assert _reader and _nest and _view and _rays is not None
    return march(_reader, _nest, _view, _rays[chunk], _steps)


def march_all(
    reader: Reader,
    nest: sky_map.Nest,
    view: View,
    rays: np.ndarray,
    workers: int,
    steps: int = STEPS,
) -> np.ndarray:
    """`march` in forked workers. Workers inherit the textures."""
    global _reader, _nest, _view, _rays, _steps
    size = 4096
    chunks = [slice(at, at + size) for at in range(0, len(rays), size)]
    _reader, _nest, _view, _rays, _steps = reader, nest, view, rays, steps
    try:
        out = np.concatenate(list(forked_stream(_rays_job, chunks, workers)))
    finally:
        _reader = _nest = _view = _rays = None
        _steps = STEPS
    return out
