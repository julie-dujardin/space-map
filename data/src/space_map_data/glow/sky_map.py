"""A NumPy copy of the sky map that the star shader reads.

The grid takes the Sun's dust out of each star with the column the shader reads,
so stars, glow and render share one dust. The map here is built as
`frontend/src/lib/scene/dust/march.ts` builds it: the exported nest, hardware
LINEAR on the codes and then the decode, the finest level first, the step law of
`layout.ts`, and the mean of the eight jittered passes of the `high` plan. A read
is `dustColumn` of `lookup.ts`.

Positions are on nest axes, in pc from the Sun.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from space_map_data.dust.march import linear_fetch
from space_map_data.dust.parallel import forked_map
from space_map_data.export.extrasolar import container
from space_map_data.utils.paths import EXTRASOLAR_DIR

SIZE = 256
SLICES = 24
SLICE_STEPS = 3
STEPS = SLICES * SLICE_STEPS
BOX = np.array((20_000.0, 20_000.0, 3_000.0))
NEAR_PC = 10.0
PASSES = 8


@dataclass(frozen=True)
class NestLevel:
    half: np.ndarray
    size: np.ndarray
    floor: float
    span: float
    # uint8, index order [iz, iy, ix], as uploaded.
    codes: np.ndarray


@dataclass(frozen=True)
class Nest:
    # Coarse to fine.
    levels: tuple[NestLevel, ...]
    # M with v_icrs = M v_nest.
    rotation: np.ndarray
    token: str


def nest_metadata(root: Path = EXTRASOLAR_DIR) -> dict:
    """The metadata of the served nest. It holds the token and the frame, so a step
    that needs only those does not read the volumes."""
    return json.loads((root / "v1" / "dust" / "metadata.json").read_text())


def load_nest(tier: str = "high", root: Path = EXTRASOLAR_DIR) -> Nest:
    """The nest as a client reads it from the export."""
    directory = root / "v1" / "dust"
    metadata = nest_metadata(root)
    levels = []
    for entry in metadata["levels"]:
        volume = container.read(directory / entry[tier]["path"])
        nx, ny, nz = entry[tier]["size"]
        levels.append(
            NestLevel(
                np.array(entry["half_extent_pc"], np.float64),
                np.array((nx, ny, nz)),
                entry["floor"],
                float(np.log1p(entry["top"] / entry["floor"])),
                volume.numpy("codes").reshape(nz, ny, nx),
            )
        )
    return Nest(tuple(levels), nest_rotation(metadata), metadata["token"])


def nest_rotation(metadata: dict) -> np.ndarray:
    """M with v_icrs = M v_nest."""
    return np.array(metadata["frame"]["rotation_to_icrs"], np.float64)


def _fetch(level: NestLevel, points: np.ndarray) -> np.ndarray:
    """LINEAR on the codes, clamped to the edge, then the decode."""
    unit = (points + level.half) / (2 * level.half)
    codes = linear_fetch(level.codes.transpose(2, 1, 0), unit)
    return level.floor * np.expm1(codes / 255 * level.span)


def density(nest: Nest, points: np.ndarray) -> np.ndarray:
    """A0 in mag/pc at each point of an (n, 3) array, the finest level first."""
    out = np.zeros(len(points), np.float32)
    todo = np.ones(len(points), bool)
    for level in reversed(nest.levels):
        inside = todo & (np.abs(points) <= level.half).all(axis=1)
        if inside.any():
            out[inside] = _fetch(level, points[inside])
            todo &= ~inside
    return out


def uv_directions(u: np.ndarray, v: np.ndarray, size: int = SIZE) -> np.ndarray:
    """`dustOctDirection` of texture coordinates, for a map `size` texels wide."""
    qx = ((u - 1 / size) * size / (size - 2) - 0.5) * 2
    qy = ((v - 1 / size) * size / (size - 2) - 0.5) * 2
    past = np.abs(qx) > 1
    qx, qy = (
        np.where(past, 2 * np.where(qx >= 0, 1.0, -1.0) - qx, qx),
        np.where(past, -qy, qy),
    )
    past = np.abs(qy) > 1
    qx, qy = (
        np.where(past, -qx, qx),
        np.where(past, 2 * np.where(qy >= 0, 1.0, -1.0) - qy, qy),
    )
    z = 1 - np.abs(qx) - np.abs(qy)
    sx, sy = np.where(qx >= 0, 1.0, -1.0), np.where(qy >= 0, 1.0, -1.0)
    under = z < 0
    x = np.where(under, (1 - np.abs(qy)) * sx, qx)
    y = np.where(under, (1 - np.abs(qx)) * sy, qy)
    d = np.stack((x, y, z), axis=-1)
    return d / np.linalg.norm(d, axis=-1, keepdims=True)


def texel_directions(size: int = SIZE) -> np.ndarray:
    """The unit direction of each texel, shape (size, size, 3), by [row, column]."""
    centres = (np.arange(size) + 0.5) / size
    return uv_directions(*np.meshgrid(centres, centres), size)


def box_span(origin: np.ndarray, d: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """`dustBoxSpan`: where each ray enters and leaves the box of the data."""
    m = 1.0 / (d + 1e-7)
    n = m * origin
    k = np.abs(m) * BOX
    near = np.maximum((-n - k).max(axis=-1), 0.0)
    return near, (-n + k).min(axis=-1)


def slice_scale(near: np.ndarray) -> np.ndarray:
    return np.maximum(NEAR_PC, near)


def slice_span(near: np.ndarray, far: np.ndarray) -> np.ndarray:
    return np.log1p(np.maximum(far - near, 1.0) / slice_scale(near))


def pass_jitter(index: int, passes: int) -> float:
    """`passJitter` of `star-dust.ts`."""
    f = 0.5 / passes
    bit = 0.5
    while index:
        if index & 1:
            f += bit
        index >>= 1
        bit /= 2
    return f


# Forked workers read these.
_nest: Nest | None = None
_origin: np.ndarray | None = None
_directions: np.ndarray | None = None


def _march_row(row: int) -> np.ndarray:
    """The columns of one texture row, shape (SLICES + 1, SIZE)."""
    assert _nest is not None and _origin is not None and _directions is not None
    d = _directions[row]
    near, far = box_span(_origin, d)
    out = np.zeros((SLICES + 1, SIZE))
    used = far > near
    if not used.any():
        return out
    d = d[used]
    near = near[used]
    scale = slice_scale(near)
    lnq = slice_span(near, far[used]) / STEPS
    for index in range(PASSES):
        e = scale * np.exp(pass_jitter(index, PASSES) * lnq)
        step = np.exp(lnq)
        total = np.zeros(len(d))
        for i in range(SLICES):
            for _ in range(SLICE_STEPS):
                at = _origin + d * (near + e - scale)[:, None]
                total += density(_nest, at) * e * lnq
                e *= step
            out[i + 1, used] += total
    return out / PASSES


def build_map(nest: Nest, origin: np.ndarray, workers: int) -> np.ndarray:
    """The map of a viewpoint, shape (SLICES + 1, SIZE, SIZE), the column in mag at
    550 nm from `origin` to the end of each slice."""
    global _nest, _origin, _directions
    _nest, _origin, _directions = (
        nest,
        np.asarray(origin, np.float64),
        texel_directions(),
    )
    try:
        rows = forked_map(_march_row, range(SIZE), workers)
    finally:
        _nest = _origin = _directions = None
    return np.stack(rows, axis=1).astype(np.float32)


def map_uv(d: np.ndarray, size: int = SIZE) -> tuple[np.ndarray, np.ndarray]:
    """`dustOctUv`, for an (n, 3) array of unit directions."""
    scale = 1.0 / np.abs(d).sum(axis=1)
    qx, qy = d[:, 0] * scale, d[:, 1] * scale
    sx, sy = np.where(qx >= 0, 1.0, -1.0), np.where(qy >= 0, 1.0, -1.0)
    under = d[:, 2] < 0
    x = np.where(under, (1 - np.abs(qy)) * sx, qx)
    y = np.where(under, (1 - np.abs(qx)) * sy, qy)
    scale_uv = (size - 2) / size
    return (x * 0.5 + 0.5) * scale_uv + 1 / size, (y * 0.5 + 0.5) * scale_uv + 1 / size


def read_map(sky: np.ndarray, origin: np.ndarray, at: np.ndarray) -> np.ndarray:
    """`dustColumn`: the column from the map's origin to `at`, an (n, 3) array of
    offsets from that origin."""
    r = np.linalg.norm(at, axis=1)
    safe = r > 1e-6
    d = np.zeros_like(at)
    d[:, 2] = 1.0
    d[safe] = at[safe] / r[safe, None]
    near, far = box_span(np.asarray(origin, np.float64), d)
    place = np.log1p(np.maximum(r - near, 0.0) / slice_scale(near)) / slice_span(
        near, far
    )
    slice_at = np.minimum(place, 1.0) * SLICES
    first = np.minimum(slice_at.astype(np.int32), SLICES - 1)
    share = (slice_at - first).astype(np.float32)
    u, v = map_uv(d)
    tx = np.clip(u * SIZE - 0.5, 0, SIZE - 1)
    ty = np.clip(v * SIZE - 0.5, 0, SIZE - 1)
    x = np.minimum(tx.astype(np.int32), SIZE - 2)
    y = np.minimum(ty.astype(np.int32), SIZE - 2)
    fx, fy = (tx - x).astype(np.float32), (ty - y).astype(np.float32)

    def plane(k: np.ndarray) -> np.ndarray:
        return (sky[k, y, x] * (1 - fx) + sky[k, y, x + 1] * fx) * (1 - fy) + (
            sky[k, y + 1, x] * (1 - fx) + sky[k, y + 1, x + 1] * fx
        ) * fy

    return plane(first) * (1 - share) + plane(first + 1) * share
