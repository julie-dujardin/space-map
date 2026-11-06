"""Starlight scattered by dust, single scattering, as an isotropic emission term.

The light that falls on a place is the glow's light with no cut: the catalogue grid
at full depth, weighted by the catalogue's fade, plus the model's residual, through
the nest (and the far volume past it). The render's scattered emission per channel c
at a step is then

    j_scat,c = albedo_c * kappa_c * J_c,   kappa_c = K_RGB,c * A0 density / 1.086

with J the mean intensity over the sphere, stored so that j_scat is in the glow's
unit (display flux of M = 0 at 10 pc per pc^3): J here is the mean over directions
of the line integral of j T ds, in flux per pc^2.

Albedo per channel is Draine's for the Weingartner & Draine Milky Way dust, R_V =
3.1 (`kext_albedo_WD_MW_3.1_60_D03.all`), at the wavelengths of K_RGB.
"""

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from space_map_data.dust.far import StoredFar
from space_map_data.dust.march import linear_fetch
from space_map_data.dust.nest import fade_out
from space_map_data.dust.parallel import forked_stream
from space_map_data.emission import project
from space_map_data.galaxy import volumes
from space_map_data.galaxy.residual import StoredResidual
from space_map_data.glow import form, light, sky_map
from space_map_data.glow.march import Textures

# Draine (2003) WD01 R_V = 3.1 at 612, 549 and 464 nm, the wavelengths of K_RGB.
ALBEDO = np.array((0.6757, 0.6774, 0.6710))
ASYMMETRY = np.array((0.5124, 0.5376, 0.5611))
TAU_PER_MAG = 1.0 / 1.0857362047581294
# The cut of the brightest edge of the grid: every star.
FULL_DEPTH = -20.0
# The model's inner box holds the disc and the dust; J lives on its layout.
J_BOX = volumes.INNER_HIGH
J_SIZES = {"high": (128, 128, 16), "low": (64, 64, 8)}
STEP_START_PC = 5.0
END_PC = 60_000.0


class Medium(Protocol):
    def light(self, points: np.ndarray) -> np.ndarray: ...

    def dust(self, points: np.ndarray) -> np.ndarray: ...


@dataclass
class Field:
    """What a ray reads: the glow's light at full depth, and the dust."""

    grid: Textures
    model: StoredResidual
    nest: sky_map.Nest
    far: StoredFar
    # The catalogue's fade from the Sun (pc), or None for weight 1.
    fade: tuple[float, float] | None

    def weight(self, points: np.ndarray) -> np.ndarray:
        if self.fade is None:
            return np.ones(len(points))
        return fade_out(np.linalg.norm(points, axis=1), *self.fade)

    def light(self, points: np.ndarray) -> np.ndarray:
        """Flux density per pc^3 and channel, no dust, shape (n, 3)."""
        out = self.model.read(points)
        w = self.weight(points)
        held = w > 0
        if held.any():
            values = self.grid.filtered(points[held])
            cut = np.full(int(held.sum()), FULL_DEPTH)
            out[held] += w[held, None] * form.read_values(values, cut, self.grid.table)
        return out

    def dust(self, points: np.ndarray) -> np.ndarray:
        return project.dust(self.nest, self.far, points)


def direction_set(longitudes: int, latitudes: int, squeeze: float = 3.0):
    """Unit vectors and weights (summing to 1) of a product grid on the sphere, its
    latitudes close together at the Galactic plane, where the light is."""
    t = (np.arange(latitudes) + 0.5) / latitudes * 2 - 1
    edges = np.linspace(-1, 1, latitudes + 1)
    mu = np.sinh(squeeze * t) / np.sinh(squeeze)
    mu_edges = np.sinh(squeeze * edges) / np.sinh(squeeze)
    lam = (np.arange(longitudes) + 0.5) / longitudes * 2 * np.pi
    m, lm = np.meshgrid(mu, lam, indexing="ij")
    cos_b = np.sqrt(1 - m**2)
    d = np.stack((cos_b * np.cos(lm), cos_b * np.sin(lm), m), axis=-1).reshape(-1, 3)
    w = np.repeat(np.diff(mu_edges), longitudes) / (2 * longitudes)
    return d, w


def step_edges(steps: int, end: float = END_PC) -> np.ndarray:
    lnq = np.log1p(end / STEP_START_PC) / steps
    return STEP_START_PC * np.expm1(np.arange(steps + 1) * lnq)


def radiance(
    field: Medium, points: np.ndarray, d: np.ndarray, edges: np.ndarray
) -> np.ndarray:
    """The line integral of j T ds toward the point from each direction, shape
    (points, directions, 3). T takes K_RGB per channel."""
    n, k = len(points), len(d)
    origin = np.repeat(points, k, axis=0)
    rays = np.tile(d, (n, 1))
    total = np.zeros((n * k, 3))
    column = np.zeros(n * k)
    for i in range(len(edges) - 1):
        ds = edges[i + 1] - edges[i]
        p = origin + rays * (0.5 * (edges[i] + edges[i + 1]))
        half = field.dust(p) * ds / 2
        column += half
        seen = 10.0 ** (-0.4 * light.K_RGB[None, :] * column[:, None])
        total += field.light(p) * seen * ds
        column += half
    return total.reshape(n, k, 3)


def mean_intensity(
    field: Medium, points: np.ndarray, d: np.ndarray, w: np.ndarray, edges: np.ndarray
) -> np.ndarray:
    """J per channel at each point, shape (n, 3)."""
    return np.einsum("nkc,k->nc", radiance(field, points, d, edges), w)


def scattered(field: Field, points: np.ndarray, j: np.ndarray) -> np.ndarray:
    """The isotropic scattered emission per channel at points, from J there."""
    kappa = light.K_RGB[None, :] * field.dust(points)[:, None] * TAU_PER_MAG
    return ALBEDO[None, :] * kappa * j


def henyey_greenstein(cos_theta: np.ndarray, g: np.ndarray) -> np.ndarray:
    """The phase function per channel, normalised to 1 over the sphere, (..., 3)."""
    c = np.asarray(cos_theta)[..., None]
    return (1 - g**2) / (4 * np.pi * (1 + g**2 - 2 * g * c) ** 1.5)


# Forked workers read these.
_job: tuple | None = None


def _chunk(chunk: slice) -> np.ndarray:
    assert _job is not None
    field, points, d, w, edges = _job
    return mean_intensity(field, points[chunk], d, w, edges)


def mean_intensity_all(
    field: Field,
    points: np.ndarray,
    d: np.ndarray,
    w: np.ndarray,
    edges: np.ndarray,
    workers: int,
    size: int = 32,
) -> np.ndarray:
    """`mean_intensity` over many points in forked workers."""
    global _job
    _job = (field, points, d, w, edges)
    chunks = [slice(at, at + size) for at in range(0, len(points), size)]
    try:
        return np.concatenate(list(forked_stream(_chunk, chunks, workers)))
    finally:
        _job = None


def voxel_centres(box: volumes.Box, size: tuple[int, int, int]) -> np.ndarray:
    """The centre of each voxel of `box` at `size`, nest axes, [x, y, z, 3]."""
    sized = volumes.Box(box.half, size, box.z_scale)
    x = sized.edges(0)
    y = sized.edges(1)
    centre = np.array(volumes.CENTRE)
    xc = 0.5 * (x[1:] + x[:-1]) + centre[0]
    yc = 0.5 * (y[1:] + y[:-1]) + centre[1]
    # The middle of a slice in its texture coordinate, as LINEAR samples it.
    w = (np.arange(size[2]) + 0.5) / size[2]
    zc = sized.height_of(w) + centre[2]
    gx, gy, gz = np.meshgrid(xc, yc, zc, indexing="ij")
    return np.stack((gx, gy, gz), axis=-1)


# J at a point inside dust is lower than the grid's J there, which is the mean of a
# voxel of hundreds of pc: the dust shields itself. The share falls with the local
# density with little scatter, so a curve in log10 density (A0 mag/pc) carries it.
SHIELD_NODES = np.arange(-5.0, 0.01, 0.5)
SHIELD_POINTS = 1500

# The colour table of J: Galactocentric radius in even steps, and distance from the
# Sun even in log(1 + d / COLOUR_D_SCALE_PC). Near the Sun the catalogue's light is
# bluer than the model's, so the colour follows both.
COLOUR_RADII = 11
COLOUR_R_MAX_PC = 30_000.0
COLOUR_DISTANCES = 8
COLOUR_D_SCALE_PC = 1000.0
COLOUR_D_MAX_PC = 40_000.0


@dataclass(frozen=True)
class JForm:
    """How J is stored: half floats times `scale`, either the three channels or
    R + G + B with the colour of a table in radius and distance from the Sun."""

    channels: int
    scale: float
    # [distance node][radius node], rows summing to 1.
    table: tuple[tuple[tuple[float, ...], ...], ...] = ()
    # J inside dust over the grid's J, at each of `SHIELD_NODES`.
    shield: tuple[float, ...] = ()

    def record(self) -> dict:
        return {
            "channels": self.channels,
            "texture_scale": self.scale,
            "shield": {
                "log10_density_nodes": SHIELD_NODES.tolist(),
                "factor": list(self.shield),
            },
            "colour": {
                "radii": COLOUR_RADII,
                "r_max_pc": COLOUR_R_MAX_PC,
                "distances": COLOUR_DISTANCES,
                "d_scale_pc": COLOUR_D_SCALE_PC,
                "d_max_pc": COLOUR_D_MAX_PC,
                "rgb": [[list(cell) for cell in row] for row in self.table],
            },
        }

    def shielding(self, density: np.ndarray) -> np.ndarray:
        """The share of the grid's J that dust of `density` (A0 mag/pc) sees."""
        if not self.shield:
            return np.ones(len(density))
        at = np.log10(np.maximum(density, 1e-12))
        return np.interp(at, SHIELD_NODES, np.array(self.shield))

    def colour(self, points: np.ndarray) -> np.ndarray:
        """Bilinear in the table, both coordinates clamped, as a texture reads it."""
        s, t = colour_coordinates(points)
        table = np.array(self.table)
        i = np.minimum(s.astype(int), COLOUR_RADII - 2)
        k = np.minimum(t.astype(int), COLOUR_DISTANCES - 2)
        fs, ft = (s - i)[:, None], (t - k)[:, None]
        low = table[k, i] * (1 - fs) + table[k, i + 1] * fs
        high = table[k + 1, i] * (1 - fs) + table[k + 1, i + 1] * fs
        return low * (1 - ft) + high * ft


def colour_coordinates(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The table's coordinates in nodes, clamped: radius, then distance."""
    g = points - np.array(volumes.CENTRE)
    r = np.hypot(g[:, 0], g[:, 1])
    d = np.linalg.norm(points, axis=1)
    s = np.clip(r / COLOUR_R_MAX_PC * (COLOUR_RADII - 1), 0, COLOUR_RADII - 1)
    t = np.log1p(d / COLOUR_D_SCALE_PC) / np.log1p(COLOUR_D_MAX_PC / COLOUR_D_SCALE_PC)
    return s, np.clip(t * (COLOUR_DISTANCES - 1), 0, COLOUR_DISTANCES - 1)


def store_j(
    j: np.ndarray,
    channels: int,
    weight: np.ndarray | None = None,
    shield: tuple[float, ...] = (),
) -> JForm:
    """The form of a J grid [x, y, z, 3] on `J_BOX`: its scale, and with one channel
    the colour table, a least-squares fit of each voxel's colour by `weight` on the
    table's bilinear weights."""
    from scipy.sparse import coo_matrix, diags
    from scipy.sparse.linalg import lsqr

    from space_map_data.emission import encode

    total = j.sum(axis=-1)
    scale = encode.scale_of(j if channels == 3 else total)
    if channels == 3:
        return JForm(3, scale, shield=shield)
    assert weight is not None
    centres = voxel_centres(J_BOX, j.shape[:3]).reshape(-1, 3)
    s, t = colour_coordinates(centres)
    i = np.minimum(s.astype(int), COLOUR_RADII - 2)
    k = np.minimum(t.astype(int), COLOUR_DISTANCES - 2)
    fs, ft = s - i, t - k
    n = len(centres)
    rows, cols, vals = [], [], []
    for dk, wk in ((0, 1 - ft), (1, ft)):
        for di, wi in ((0, 1 - fs), (1, fs)):
            rows.append(np.arange(n))
            cols.append((k + dk) * COLOUR_RADII + i + di)
            vals.append(wk * wi)
    a = coo_matrix(
        (np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
        shape=(n, COLOUR_RADII * COLOUR_DISTANCES),
    ).tocsr()
    share = j.reshape(-1, 3) / np.maximum(total.reshape(-1), 1e-30)[:, None]
    root = np.sqrt(weight.reshape(-1) / weight.sum() + 1e-12)
    weighted = diags(root) @ a
    table = np.stack(
        [lsqr(weighted, root * share[:, c], damp=1e-4)[0] for c in range(3)], axis=-1
    )
    # Nodes no voxel weighs keep the damped fit's pull toward 0: give them the mean.
    mean = (weight.reshape(-1)[:, None] * share).sum(0) / weight.sum()
    held = np.asarray(abs(a).T @ weight.reshape(-1)).ravel() > 0
    table[~held] = mean
    table = np.maximum(table, 1e-4)
    table /= table.sum(axis=1, keepdims=True)
    grid = table.reshape(COLOUR_DISTANCES, COLOUR_RADII, 3)
    return JForm(
        1,
        scale,
        tuple(
            tuple(tuple(round(float(v), 6) for v in cell) for cell in row)
            for row in grid
        ),
        shield,
    )


def voxel_volumes(box: volumes.Box) -> np.ndarray:
    dx, dy, dz = (np.diff(box.edges(axis)) for axis in range(3))
    return dx[:, None, None] * dy[None, :, None] * dz[None, None, :]


def voxel_dust(
    field: Field, box: volumes.Box, points: int = 8, seed: int = 0
) -> np.ndarray:
    """The mean dust of each voxel of `box` at random points, [x, y, z]."""
    rng = np.random.default_rng(seed)
    ex, ey, ez = (box.edges(axis) for axis in range(3))
    out = np.zeros(box.size)
    for _ in range(points):
        u = rng.random((*box.size, 3))
        x = ex[:-1, None, None] + u[..., 0] * np.diff(ex)[:, None, None]
        y = ey[None, :-1, None] + u[..., 1] * np.diff(ey)[None, :, None]
        z = ez[None, None, :-1] + u[..., 2] * np.diff(ez)[None, None, :]
        p = np.stack((x, y, z), axis=-1).reshape(-1, 3) + np.array(volumes.CENTRE)
        out += field.dust(p).reshape(box.size) / points
    return out


def j_bits(j: np.ndarray, form: JForm) -> np.ndarray:
    from space_map_data.emission import encode

    values = j if form.channels == 3 else j.sum(axis=-1)
    return encode.half_bits(values.astype(np.float64) * form.scale)


@dataclass
class StoredJ:
    """J as the render reads it: LINEAR on the half floats of the box, the colour
    from the form, 0 outside the box."""

    form: JForm
    values: np.ndarray
    box: volumes.Box

    def read(self, points: np.ndarray) -> np.ndarray:
        out = np.zeros((len(points), 3))
        inside = self.box.inside(points)
        if inside.any():
            p = points[inside]
            got = linear_fetch(self.values, self.box.uvw(p)) / self.form.scale
            out[inside] = (
                got if self.form.channels == 3 else got[:, None] * self.form.colour(p)
            )
        return out


def dust_weighted_points(
    field: Medium,
    half: np.ndarray,
    count: int,
    rng: np.random.Generator,
    accept: float = 0.05,
) -> np.ndarray:
    """Points in a box about the Sun drawn in proportion to dust, up to `accept`
    mag/pc, past which every point is kept."""
    found: list[np.ndarray] = []
    while sum(len(p) for p in found) < count:
        p = rng.uniform(-1.0, 1.0, (200_000, 3)) * half
        keep = rng.random(len(p)) < field.dust(p) / accept
        found.append(p[keep])
    return np.concatenate(found)[:count]


def shield_curve(density: np.ndarray, ratio: np.ndarray) -> np.ndarray:
    """The median ratio in each half-dex of density about each node, then made to
    fall with density and to be 1 where the ratio has no points below."""
    at = np.log10(np.maximum(density, 1e-12))
    out = np.ones(len(SHIELD_NODES))
    for i, node in enumerate(SHIELD_NODES):
        near = np.abs(at - node) <= 0.25
        if near.sum() >= 10:
            out[i] = np.median(ratio[near])
        elif i > 0:
            out[i] = out[i - 1]
    return np.minimum.accumulate(np.minimum(out, 1.0))
