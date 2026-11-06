"""H-alpha near the Sun: McCallum et al. 2025's cube on the nest's level 2 box,
scaled per sightline so that its projection through the nest's dust meets
Finkbeiner 2003.

The cube places the emission and Finkbeiner fixes the total: McCallum's model has
too little H-alpha and too large H II regions. Finkbeiner's sky has passed through
dust and holds light this cube does not: the far H II regions and H-alpha scattered
by dust. So the target of the local cube is

    T = F (1 - SCATTERED_SHARE) - far

with `far` the regions of `regions.py` as seen through the same dust. The factor is
the ratio of T to the cube's dimmed projection, both smoothed on the sky with a
Gaussian of `SMOOTH_DEG`, held within `FACTOR_LIMIT` either way. The cube holds the
intrinsic emission, and the render's dust dims it once.
"""

import numpy as np
from scipy.spatial import KDTree

from space_map_data.emission import lines, sky, sources

# The level 2 box of the nest, which is McCallum's box.
HALF_PC = sources.CUBE_HALF_PC
TIER_SIZES = {"high": 256, "low": 128}
# Of the observed H-alpha at high latitude, the share scattered by dust: 19 +- 4%
# (Brandt & Draine 2012), 18% at abs(b) > 30 deg in McCallum et al. 2025's model.
SCATTERED_SHARE = 0.19
SMOOTH_DEG = 2.0
FACTOR_NSIDE = 64
FACTOR_LIMIT = 4.0
SKY_NSIDE = 128
# Rays from the Sun to the corner of the box, in even steps.
STEP_PC = 2.5
END_PC = HALF_PC * np.sqrt(3.0)


def bare_cube() -> np.ndarray:
    """McCallum's cube at the `high` size in the stored unit, [x, y, z]."""
    factor = sources.CUBE_SIZE // TIER_SIZES["high"]
    return lines.emissivity_to_display(sources.cube_blocks(factor)).astype(np.float32)


def finkbeiner(nside: int = SKY_NSIDE) -> np.ndarray:
    """Finkbeiner's sky in rayleighs, as the mean over each pixel of `nside`."""
    return sky.degrade(sources.finkbeiner_sky(), nside)


def target(observed: np.ndarray, far: np.ndarray) -> np.ndarray:
    return observed * (1.0 - SCATTERED_SHARE) - far


def factor_map(
    projection: np.ndarray,
    wanted: np.ndarray,
    sigma_deg: float = SMOOTH_DEG,
    limit: float = FACTOR_LIMIT,
) -> np.ndarray:
    """The scale of each sightline on `FACTOR_NSIDE`: the ratio of the smoothed maps,
    within [1 / limit, limit]. Where the cube sends nothing the factor is 1."""
    p = sky.smooth(sky.degrade(projection, FACTOR_NSIDE), sigma_deg)
    t = sky.smooth(sky.degrade(wanted, FACTOR_NSIDE), sigma_deg)
    factor = np.where(p > 0, t / np.where(p > 0, p, 1.0), 1.0)
    return np.clip(factor, 1.0 / limit, limit)


def apply_factor(cube: np.ndarray, factor: np.ndarray) -> np.ndarray:
    """The cube with each voxel times the factor toward its centre, in slabs of x."""
    size = cube.shape[0]
    centres = (np.arange(size) + 0.5) / size * 2 * HALF_PC - HALF_PC
    tree = KDTree(sky.directions(int(np.sqrt(len(factor) / 12))))
    out = np.empty(cube.shape, np.float32)
    slab = max(1, (1 << 20) // size**2)
    for start in range(0, size, slab):
        x, y, z = np.meshgrid(
            centres[start : start + slab], centres, centres, indexing="ij"
        )
        p = np.stack((x, y, z), axis=-1)
        d = (p / np.linalg.norm(p, axis=-1, keepdims=True)).reshape(-1, 3)
        scale = sky.interpolate(factor, d, tree).reshape(x.shape)
        out[start : start + slab] = cube[start : start + slab] * scale
    return out


def block_mean(cube: np.ndarray) -> np.ndarray:
    n = cube.shape[0] // 2
    return cube.reshape(n, 2, n, 2, n, 2).mean(axis=(1, 3, 5), dtype="f8").astype("f4")
