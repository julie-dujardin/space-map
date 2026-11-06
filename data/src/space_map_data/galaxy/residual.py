"""The residual: model light less the catalogue's, where the model holds more.

`j_glow = j_cat(fainter than M_cut) + max(0, j_model - j_cat,total)`. The catalogue
term is the light grid of the glow build, read with LINEAR as the march reads it, at
the same points as the model, so a voxel compares like with like. The comparison
takes the light of both over a few voxels (`build.COMPARE_SIGMA`), and the residual
keeps the model's shape: per voxel the model times one less the catalogue's share.

Stored form (see `model_data.md`): one channel, R + G + B, in half floats. Its colour
is the model's, from a table by Galactocentric radius and height, so the clamp works
on light and cannot tint. The four-channel form clamps each channel and is kept as
the comparison.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from space_map_data.dust.march import linear_fetch
from space_map_data.dust.nest import fade_out
from space_map_data.galaxy.model import Model
from space_map_data.glow import build as glow_build
from space_map_data.glow import sky_map

# The colour table: bilinear in radius from the centre (cylindrical) and height from
# the plane, at these nodes; past `TABLE_REACH_PC` (spherical) by shells, the Clouds'
# among them. 65 vec3 beside the glow's 81 vec4 fit the 224 uniforms a fragment shader
# is sure of, and take no texture fetch.
TABLE_RADIUS_STEP_PC = 1000.0
TABLE_RADII = 31
TABLE_HEIGHT_STEP_PC = 1000.0
TABLE_HEIGHTS = 2
TABLE_REACH_PC = 30_000.0
TABLE_SHELLS_PC = (45_000.0, 55_000.0)
TABLE_SIZE = TABLE_RADII * TABLE_HEIGHTS + len(TABLE_SHELLS_PC) + 1
# The catalogue's weight falls from 1 to 0 over these distances from the Sun, in the
# residual and in the light the march takes from the grid. Past about 3 kpc the
# catalogue is a thin sample of luminous stars along clear sightlines, with distance
# errors, and from outside its spokes draw a ball over the Galaxy; from the Sun the
# sky moves by 2% at most with the fade. None keeps it at 1.
CATALOGUE_FADE_PC: tuple[float, float] | None = (2000.0, 4000.0)


def catalogue_weight(distance: np.ndarray) -> np.ndarray:
    if CATALOGUE_FADE_PC is None:
        return np.ones_like(distance)
    start, end = CATALOGUE_FADE_PC
    return fade_out(distance, start, end)


@dataclass
class CatalogueGrid:
    """The glow build's light of all stars per channel, as the march reads it."""

    tier: str
    volume: np.ndarray

    @classmethod
    def load(cls, build: Path, tier: str) -> CatalogueGrid:
        channels = np.load(build / glow_build.channels_name(tier))
        # Stored [shell, row, column, channel]; a fetch takes [x, y, z].
        return cls(tier, np.ascontiguousarray(channels.transpose(2, 1, 0, 3)))

    def read(self, points: np.ndarray) -> np.ndarray:
        """Flux density per pc^3 and channel at points on nest axes, shape (n, 3)."""
        grid = glow_build.GRIDS[self.tier]
        r = np.linalg.norm(points, axis=1)
        d = points / np.maximum(r, 1e-9)[:, None]
        u, v = sky_map.map_uv(d, grid.size)
        w = np.log1p(r / grid.scale) / grid.span
        out = linear_fetch(self.volume, np.stack((u, v, w), axis=1)).astype(np.float64)
        out[r > grid.reach] = 0.0
        return out


def sampler(model: Model, grids: dict[str, CatalogueGrid]):
    """Model RGB, then each tier's catalogue RGB weighted by distance, per point."""

    def read(points: np.ndarray) -> np.ndarray:
        x, y, z = points.T
        weight = catalogue_weight(np.linalg.norm(points, axis=1))[:, None]
        parts = [model.rgb(x, y, z)]
        parts += [grids[tier].read(points) * weight for tier in sorted(grids)]
        return np.concatenate(parts, axis=1)

    return read


def table_weights(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The table entries of each point and their weights, shape (n, 4) each, as the
    shader reads the table."""
    from space_map_data.galaxy.volumes import CENTRE

    g = points - np.array(CENTRE)
    r = np.linalg.norm(g, axis=1)
    R = np.hypot(g[:, 0], g[:, 1])
    a = np.clip(R / TABLE_RADIUS_STEP_PC, 0, TABLE_RADII - 1.001)
    b = np.clip(np.abs(g[:, 2]) / TABLE_HEIGHT_STEP_PC, 0, TABLE_HEIGHTS - 1.001)
    i, j = a.astype(int), b.astype(int)
    fa, fb = a - i, b - j
    index = np.stack(
        (
            j * TABLE_RADII + i,
            j * TABLE_RADII + i + 1,
            (j + 1) * TABLE_RADII + i,
            (j + 1) * TABLE_RADII + i + 1,
        ),
        axis=1,
    )
    weight = np.stack(
        ((1 - fa) * (1 - fb), fa * (1 - fb), (1 - fa) * fb, fa * fb), axis=1
    )
    far = r >= TABLE_REACH_PC
    shell = TABLE_RADII * TABLE_HEIGHTS + np.searchsorted(TABLE_SHELLS_PC, r[far])
    index[far] = shell[:, None]
    weight[far] = (1.0, 0.0, 0.0, 0.0)
    return index, weight


def colour_table(
    centres: np.ndarray, residual_rgb: np.ndarray, model_rgb: np.ndarray
) -> np.ndarray:
    """The chromaticity of the residual's light at each table entry, gathered with
    the weights the shader reads it with; entries the residual misses take the
    model's colour. Rows sum to 1."""
    index, weight = table_weights(centres)
    table = np.zeros((TABLE_SIZE, 3))
    fallback = np.zeros((TABLE_SIZE, 3))
    for k in range(4):
        for c in range(3):
            table[:, c] += np.bincount(
                index[:, k], residual_rgb[:, c] * weight[:, k], TABLE_SIZE
            )
            fallback[:, c] += np.bincount(
                index[:, k], model_rgb[:, c] * weight[:, k], TABLE_SIZE
            )
    empty = table.sum(axis=1) <= 0
    table[empty] = fallback[empty]
    table[table.sum(axis=1) <= 0] = 1.0
    return table / table.sum(axis=1, keepdims=True)


def table_colour(table: np.ndarray, points: np.ndarray) -> np.ndarray:
    """The table's chromaticity at points, as the shader reads it."""
    index, weight = table_weights(points)
    return (table[index] * weight[..., None]).sum(axis=1)


def voxel_centres(box) -> np.ndarray:
    from space_map_data.galaxy.volumes import CENTRE

    ex, ey, ez = (box.edges(a) for a in range(3))
    cx, cy, cz = (0.5 * (e[1:] + e[:-1]) for e in (ex, ey, ez))
    X, Y, Z = np.meshgrid(cx, cy, cz, indexing="ij")
    return np.stack((X, Y, Z), axis=-1).reshape(-1, 3) + np.array(CENTRE)


@dataclass
class StoredResidual:
    """The encoded residual of one tier, read as the march reads it: the inner box
    where it holds a point, else the outer one, LINEAR, then the colour table."""

    boxes: dict
    volumes: dict[str, np.ndarray]
    scale: float
    table: np.ndarray

    @classmethod
    def load(cls, out: Path, tier: str) -> StoredResidual:
        import json

        from space_map_data.galaxy import build, volumes
        from space_map_data.glow import encode

        raw = json.loads((out / build.ENCODING_FILE).read_text())
        table = np.array(json.loads((out / build.TABLE_FILE).read_text())["rgb"])
        stored = {
            box: encode.bits_to_values(np.load(out / build.bits_name(box, tier)))
            for box in build.BOXES
        }
        return cls(volumes.TIERS[tier], stored, raw["scale"], table)

    def light(self, points: np.ndarray) -> np.ndarray:
        """R + G + B flux density per pc^3 at points on nest axes."""
        inner, outer = self.boxes["inner"], self.boxes["outer"]
        out = np.zeros(len(points))
        held = inner.inside(points)
        rest = ~held & outer.inside(points)
        for box, chosen in ((inner, held), (outer, rest)):
            if chosen.any():
                name = "inner" if box is inner else "outer"
                out[chosen] = linear_fetch(self.volumes[name], box.uvw(points[chosen]))
        return out / self.scale

    def read(self, points: np.ndarray) -> np.ndarray:
        """Flux density per pc^3 and channel, shape (n, 3)."""
        return self.light(points)[:, None] * table_colour(self.table, points)
