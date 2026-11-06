"""Rays through everything the render draws past the stars, in NumPy, for the gates
and the images: starlight with no cut (the glow's light at full depth plus the
model), H-alpha near the Sun and starlight scattered by dust, each per channel and
apart, through the nest. The far H II regions are sprites: `sky.paint` lays them
on a sky.

Each light takes the transmission at its own K per channel: K_RGB for starlight and
scattered light, `lines.K_EMISSION` for the lines. Results are surface brightness in
flux of M = 0 at 10 pc per sr per channel.
"""

from dataclasses import dataclass

import numpy as np

from space_map_data.dust.parallel import forked_stream
from space_map_data.emission import lines, project, scatter, sky
from space_map_data.galaxy import volumes
from space_map_data.glow import light

AT_TEN_PC = 100.0
PARTS = ("direct", "scattered", "halpha")


@dataclass
class Scene:
    field: scatter.Field
    j: scatter.StoredJ
    halpha: project.Fetch


def log_steps(steps: int, start: float, end: float) -> tuple[np.ndarray, np.ndarray]:
    """Steps even in log(1 + s / start): sample distances and lengths, (steps,)."""
    edges = start * np.expm1(np.arange(steps + 1) / steps * np.log1p(end / start))
    return 0.5 * (edges[1:] + edges[:-1]), np.diff(edges)


def march(
    scene: Scene,
    origin: np.ndarray,
    rays: np.ndarray,
    mids: np.ndarray,
    lengths: np.ndarray,
) -> dict[str, np.ndarray]:
    """Each part per channel toward each ray, shape (n, 3). `mids` and `lengths` are
    (steps,) or (n, steps)."""
    n = len(rays)
    mids = np.broadcast_to(mids, (n, mids.shape[-1]))
    lengths = np.broadcast_to(lengths, (n, lengths.shape[-1]))
    out = {part: np.zeros((n, 3)) for part in PARTS}
    column = np.zeros(n)
    for i in range(mids.shape[1]):
        ds = lengths[:, i]
        p = origin + rays * mids[:, i : i + 1]
        rho = scene.field.dust(p)
        column += rho * ds / 2
        stars = 10.0 ** (-0.4 * light.K_RGB[None, :] * column[:, None])
        lines_seen = 10.0 ** (-0.4 * lines.K_EMISSION[None, :] * column[:, None])
        w = (ds * AT_TEN_PC)[:, None]
        out["direct"] += scene.field.light(p) * stars * w
        j = scene.j.read(p) * scene.j.form.shielding(rho)[:, None]
        kappa = light.K_RGB[None, :] * rho[:, None] * scatter.TAU_PER_MAG
        out["scattered"] += scatter.ALBEDO[None, :] * kappa * j * stars * w
        e = scene.halpha(p)
        out["halpha"] += e[:, None] * lines.COLOUR[None, :] * lines_seen * w
        column += rho * ds / 2
    return out


_job: tuple | None = None


def _chunk(chunk: slice) -> dict[str, np.ndarray]:
    assert _job is not None
    scene, origin, rays, mids, lengths = _job
    m = mids if mids.ndim == 1 else mids[chunk]
    s = lengths if lengths.ndim == 1 else lengths[chunk]
    return march(scene, origin, rays[chunk], m, s)


def march_all(scene, origin, rays, mids, lengths, workers: int, size: int = 2048):
    global _job
    _job = (scene, np.asarray(origin, np.float64), rays, mids, lengths)
    chunks = [slice(at, at + size) for at in range(0, len(rays), size)]
    try:
        parts = list(forked_stream(_chunk, chunks, workers))
    finally:
        _job = None
    return {part: np.concatenate([p[part] for p in parts]) for part in PARTS}


def sun_sky(scene: Scene, nside: int, workers: int, steps: int = 512) -> dict:
    """The sky from the Sun on a HEALPix sphere."""
    rays = sky.directions(nside)
    mids, lengths = log_steps(steps, 0.5, 100_000.0)
    return march_all(scene, np.zeros(3), rays, mids, lengths, workers)


def box_rays(origin: np.ndarray, rays: np.ndarray, box, steps: int):
    """Even steps through a `galaxy.volumes.Box` along each ray: mids and lengths,
    (n, steps). A ray that misses has zero length."""
    lo = np.array(volumes.CENTRE) - np.array(box.half)
    hi = np.array(volumes.CENTRE) + np.array(box.half)
    inv = 1.0 / np.where(np.abs(rays) < 1e-12, 1e-12, rays)
    t0 = (lo - origin) * inv
    t1 = (hi - origin) * inv
    near = np.maximum(np.minimum(t0, t1).max(axis=1), 0.0)
    far = np.maximum(np.maximum(t0, t1).min(axis=1), near)
    f = (np.arange(steps) + 0.5) / steps
    mids = near[:, None] + (far - near)[:, None] * f[None, :]
    lengths = np.repeat(((far - near) / steps)[:, None], steps, axis=1)
    return mids, lengths


def regions_from(
    found: dict, origin: np.ndarray, column: np.ndarray, nside: int
) -> np.ndarray:
    """The far regions per channel on a sky from `origin`, each dimmed by `column`
    (A0 from the origin to it): flux per sr."""
    offset = found["position"] - origin
    distance = np.linalg.norm(offset, axis=1)
    axes = offset / distance[:, None]
    flux = regions_flux(found, origin, column)
    return sky.paint(axes, found["sigma_pc"] / distance, flux, nside)


def column_between(
    field: scatter.Field, origin: np.ndarray, targets: np.ndarray, steps: int = 600
) -> np.ndarray:
    """The column A0 (mag) from `origin` to each target, in even steps."""
    return project.column_to(field.nest, field.far, targets, steps, origin)


def regions_flux(found: dict, origin: np.ndarray, column: np.ndarray) -> np.ndarray:
    """Each far region's flux per channel at `origin`, through `column`."""
    distance = np.linalg.norm(found["position"] - origin, axis=1)
    seen = (
        found["display"][:, None]
        * lines.COLOUR[None, :]
        * 10.0 ** (-0.4 * lines.K_EMISSION[None, :] * column[:, None])
    )
    return seen * AT_TEN_PC / distance[:, None] ** 2
