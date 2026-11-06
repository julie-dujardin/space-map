"""The far volume: the rest layer where level 0 does not reach.

Level 0 ends 20 kpc from the Sun, 11.7 kpc past the Galactic centre, so from
outside the dust lane would stop there. This volume holds the rest layer's own
field past that face: the rest scale times the model's dust shape, with the same
arms, warp and flare. No observed layer reaches the faces of level 0, so there the
field equals level 0. Past the near window of each sightline the scale is the
smooth base alone.

The box is the inner box of the model light (`galaxy.volumes.INNER_HIGH`), so one
texture coordinate serves both. A reader takes the volume only where level 0 does
not hold a point, so the nest and the Sun view inside it do not change. Texels
deep in level 0 hold 0. A texel within one `low` texel of a face keeps the field,
so a filtered read just outside a face reads no zeros.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from space_map_data.dust.march import linear_fetch
from space_map_data.dust.merge import merged_dir
from space_map_data.dust.nest import LEVELS
from space_map_data.dust.rest import FIELD_FILE, scale_at
from space_map_data.dust.sources import atomic_npy, file_digest
from space_map_data.export.extrasolar import container
from space_map_data.extrasolar.store import write_json
from space_map_data.galaxy import geometry, volumes
from space_map_data.utils.paths import EXTRASOLAR_DIR

logger = logging.getLogger(__name__)

FAR_HIGH = volumes.Box(
    volumes.INNER_HIGH.half, (256, 256, 32), volumes.INNER_HIGH.z_scale
)
FAR_TIERS = {"high": FAR_HIGH, "low": FAR_HIGH.halved()}
DENSITY_FILE = "far.density.npy"
RECORD_FILE = "far.json"
# The index byte of the volume files: the levels take 0 to 3.
FAR_INDEX = 4
FLOOR = 1e-6


class StaleFar(Exception):
    pass


def far_density(field: np.ndarray, points: np.ndarray) -> np.ndarray:
    """Rest density in mag/pc at points on nest axes, shape (n, 1)."""
    x, y, z = points.T
    return (scale_at(field, x, y, z) * geometry.dust_shape(x, y, z))[:, None]


def _held(edges: np.ndarray, half: float) -> np.ndarray:
    """Cells whose span, grown by one cell each way, lies within [-half, half]."""
    low = np.concatenate(([-np.inf], edges[:-2]))
    high = np.concatenate((edges[2:], [np.inf]))
    return (low >= -half) & (high <= half)


def interior(box: volumes.Box) -> np.ndarray:
    """Texels of `box` in level 0 with a margin of one texel, shape (nx, ny, nz)."""
    half = LEVELS[0].half
    held = [
        _held(box.edges(axis) + volumes.CENTRE[axis], half[axis]) for axis in range(3)
    ]
    return held[0][:, None, None] & held[1][None, :, None] & held[2][None, None, :]


def zero_interior(density: np.ndarray, tiers: dict[str, volumes.Box]) -> np.ndarray:
    """Zero the `high` texels whose `low` texel is interior, so both tiers hold the
    field near each face."""
    inside = interior(tiers["low"])
    for axis in range(3):
        inside = np.repeat(inside, 2, axis=axis)
    out = density.astype(np.float32)
    out[inside] = 0.0
    return out


def build_far(variant: str, workers: int) -> None:
    """Write the far volume of the `high` box, and `far.json` with what it read."""
    directory = merged_dir(variant)
    field_path = directory / FIELD_FILE
    field = np.load(field_path)
    box = FAR_TIERS["high"]
    baked = volumes.bake(box, lambda points: far_density(field, points), 1, workers)
    density = zero_interior(baked[..., 0], FAR_TIERS)
    atomic_npy(directory / DENSITY_FILE, density)
    write_json(
        directory / RECORD_FILE,
        {
            "rest_field": file_digest(field_path),
            "density": file_digest(directory / DENSITY_FILE),
            "far_side_arms": geometry.FAR_SIDE_ARMS,
        },
    )
    logger.info("far %s: top %.3g mag/pc", variant, float(density.max()))


def read_built(variant: str) -> np.ndarray:
    """The far density of the `high` box. It refuses a volume of another rest field."""
    directory = merged_dir(variant)
    record = json.loads((directory / RECORD_FILE).read_text())
    if record["rest_field"] != file_digest(directory / FIELD_FILE):
        raise StaleFar(f"{directory / DENSITY_FILE} is of another rest field: run far")
    if record["density"] != file_digest(directory / DENSITY_FILE):
        raise StaleFar(f"{directory / DENSITY_FILE} is not of its record: run far")
    return np.load(directory / DENSITY_FILE)


def low_tier(density: np.ndarray) -> np.ndarray:
    """The mean over 2 x 2 x 2 texels by volume, as slices differ in height."""
    return volumes.block_mean(density[..., None], FAR_TIERS["high"])[..., 0]


def uvw(points: np.ndarray, centre, half, z_scale: float) -> np.ndarray:
    """Texture coordinates of points on nest axes: linear in x and y, asinh in z."""
    d = points - np.asarray(centre)
    half = np.asarray(half)
    span = np.arcsinh(half[2] / z_scale)
    return np.column_stack(
        (
            0.5 + 0.5 * d[:, 0] / half[0],
            0.5 + 0.5 * d[:, 1] / half[1],
            0.5 + 0.5 * np.arcsinh(d[:, 2] / z_scale) / span,
        )
    )


@dataclass
class StoredFar:
    """The far volume as a client reads it from the export: 0 where level 0 holds
    the point or the box does not, else LINEAR on the codes, then the decode."""

    centre: np.ndarray
    half: np.ndarray
    z_scale: float
    floor: float
    span: float
    # uint8, index order [ix, iy, iz].
    codes: np.ndarray
    level0_half: np.ndarray

    @classmethod
    def load(cls, root: Path = EXTRASOLAR_DIR, tier: str = "high") -> StoredFar:
        directory = root / "v1" / "dust"
        metadata = json.loads((directory / "metadata.json").read_text())
        far = metadata["far"]
        nx, ny, nz = far[tier]["size"]
        codes = container.read(directory / far[tier]["path"]).numpy("codes")
        level0 = next(entry for entry in metadata["levels"] if entry["level"] == 0)
        return cls(
            np.array(far["centre_pc"], np.float64),
            np.array(far["half_extent_pc"], np.float64),
            float(far["z_scale_pc"]),
            far["floor"],
            float(np.log1p(far["top"] / far["floor"])),
            np.ascontiguousarray(codes.reshape(nz, ny, nx).transpose(2, 1, 0)),
            np.array(level0["half_extent_pc"], np.float64),
        )

    def read(self, points: np.ndarray) -> np.ndarray:
        """A0 in mag/pc at points on nest axes, shape (n, 3)."""
        out = np.zeros(len(points), np.float32)
        held = np.all(np.abs(points) <= self.level0_half, axis=1)
        inside = np.all(np.abs(points - self.centre) <= self.half, axis=1)
        chosen = inside & ~held
        if chosen.any():
            at = uvw(points[chosen], self.centre, self.half, self.z_scale)
            filtered = linear_fetch(self.codes, at)
            out[chosen] = self.floor * np.expm1(filtered / 255.0 * self.span)
        return out
