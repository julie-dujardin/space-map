"""Rays from the Sun through the nest: dust columns and the H-alpha a cube sends,
as seen. A NumPy copy of what the render's march does, with short even steps.

The dust is the exported nest, read as the shader reads it (`glow.sky_map.density`),
and the far volume where no level holds a point. H-alpha takes `K_LINE` of the ZGR23
curve at 656 nm, so the projection is dimmed once, by the render's own dust.
"""

from collections.abc import Callable

import numpy as np

from space_map_data.dust.far import StoredFar
from space_map_data.dust.march import linear_fetch
from space_map_data.dust.parallel import forked_stream
from space_map_data.emission import lines
from space_map_data.glow import sky_map

Fetch = Callable[[np.ndarray], np.ndarray]


def dust(nest: sky_map.Nest, far: StoredFar | None, points: np.ndarray) -> np.ndarray:
    """A0 in mag/pc: the finest level of the nest that holds a point, else the far
    volume."""
    out = sky_map.density(nest, points).astype(np.float64)
    if far is not None:
        held = np.zeros(len(points), bool)
        for level in nest.levels:
            held |= (np.abs(points) <= level.half).all(axis=1)
        out[~held] = far.read(points[~held])
    return out


def cube_fetch(
    cube: np.ndarray,
    half: float,
    read: Callable[[np.ndarray, np.ndarray], np.ndarray] = linear_fetch,
) -> Fetch:
    """`read` (LINEAR by default) on a cube [x, y, z] that fills the box of half extent
    `half` about the Sun, at texture coordinates; 0 outside."""

    def fetch(points: np.ndarray) -> np.ndarray:
        out = np.zeros(len(points))
        inside = (np.abs(points) <= half).all(axis=1)
        if inside.any():
            out[inside] = read(cube, (points[inside] + half) / (2 * half))
        return out

    return fetch


# Forked workers read these.
_job: tuple | None = None


def _rays(chunk: slice) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    assert _job is not None
    nest, far, fetch, rays, end, step, k = _job
    d = rays[chunk]
    seen = np.zeros(len(d))
    bare = np.zeros(len(d))
    column = np.zeros(len(d))
    for s in np.arange(step / 2, end, step):
        p = d * s
        half = dust(nest, far, p) * step / 2
        column += half
        e = fetch(p) * step
        bare += e
        seen += e * 10.0 ** (-0.4 * k * column)
        column += half
    return seen, bare, column


def from_sun(
    nest: sky_map.Nest,
    far: StoredFar | None,
    fetch: Fetch,
    rays: np.ndarray,
    end: float,
    step: float,
    workers: int,
    k: float = lines.K_LINE["halpha"],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Line integrals of `fetch` along each ray to `end` pc, as seen through the dust
    (the transmission at `k` A0) and bare, and the column to `end` (mag)."""
    global _job
    _job = (nest, far, fetch, rays, end, step, k)
    size = 2048
    chunks = [slice(at, at + size) for at in range(0, len(rays), size)]
    try:
        parts = list(forked_stream(_rays, chunks, workers))
    finally:
        _job = None
    seen, bare, column = (np.concatenate([p[i] for p in parts]) for i in range(3))
    return seen, bare, column


def column_to(
    nest: sky_map.Nest,
    far: StoredFar | None,
    targets: np.ndarray,
    steps: int = 400,
    origin: np.ndarray | None = None,
) -> np.ndarray:
    """The column A0 (mag) from `origin` (the Sun if None) to each point, in even
    steps."""
    offset = targets if origin is None else targets - origin
    r = np.linalg.norm(offset, axis=1)
    d = offset / np.maximum(r, 1e-9)[:, None]
    column = np.zeros(len(targets))
    for i in range(steps):
        s = (i + 0.5) / steps * r
        p = d * s[:, None]
        column += dust(nest, far, p if origin is None else origin + p) * r / steps
    return column
