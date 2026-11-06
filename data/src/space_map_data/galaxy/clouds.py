"""The Magellanic Clouds as model light: smooth shapes of real galaxies, each of
integral 1. Their place is the Local Volume Database's, the registry's source for
galaxies, with the distances of Pietrzyński et al. 2019 (LMC) and Graczyk et al.
2020 (SMC). They hold no dust here.
"""

from functools import cache

import numpy as np

from space_map_data.dust.nest import galactic_to_icrs
from space_map_data.galaxy import sources

# van der Marel 2001: exponential, scale 1.3 to 1.5 kpc. van der Marel 2002: sech^2
# with z0 0.27 kpc at the centre rising to 1.5 kpc at 5.5 kpc. van der Marel &
# Kallivayalil 2014, Table 1, PMs and old stars: inclination and line of nodes.
LMC_SCALE_PC = 1400.0
LMC_Z0_PC = (270.0, 1500.0, 5500.0)
LMC_INCLINATION = np.radians(34.0)
LMC_NODES = np.radians(139.1)
LMC_REACH_PC = 12_000.0
# Graczyk et al. 2020: distance 62.44 kpc; a core of about 1.5 kpc at RA 12.44, Dec
# -72.94 with 40% of the stars, the rest spread along the line of sight with a
# dispersion of about 2 kpc. Across the sky the debris takes the half-light radius of
# the Local Volume Database (Gaussian, r_h = 1.177 sigma).
SMC_DISTANCE_PC = 62_440.0
SMC_CORE = (12.44, -72.94)
SMC_CORE_SHARE = 0.4
SMC_CORE_SCALE_PC = 500.0
SMC_DEPTH_PC = 2000.0


def sky_vectors(ra_deg: float, dec_deg: float) -> tuple[np.ndarray, ...]:
    """Unit vectors on nest axes: toward the point, to the north and to the east."""
    ra, dec = np.radians(ra_deg), np.radians(dec_deg)
    toward = np.array([np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)])
    north = np.array(
        [-np.sin(dec) * np.cos(ra), -np.sin(dec) * np.sin(ra), np.cos(dec)]
    )
    east = np.array([-np.sin(ra), np.cos(ra), 0.0])
    to_nest = galactic_to_icrs().T
    return to_nest @ toward, to_nest @ north, to_nest @ east


@cache
def lmc_frame() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Centre (pc), line of nodes, in-plane axis toward the near side, and normal."""
    row = sources.lvdb_cloud("lmc")
    toward, north, east = sky_vectors(row.ra_deg, row.dec_deg)
    nodes = np.cos(LMC_NODES) * north + np.sin(LMC_NODES) * east
    # The near side lies at position angle Theta - 90 deg (van der Marel 2001).
    near = np.cos(LMC_NODES - np.pi / 2) * north + np.sin(LMC_NODES - np.pi / 2) * east
    across = np.cos(LMC_INCLINATION) * near - np.sin(LMC_INCLINATION) * toward
    return row.distance_pc * toward, nodes, across, np.cross(nodes, across)


def lmc_shape(x, y, z) -> np.ndarray:
    centre, nodes, across, normal = lmc_frame()
    p = np.stack((x, y, z), axis=-1) - centre
    a, b = p @ nodes, p @ across
    rho = np.hypot(a, b)
    height = p @ normal
    low, high, at = LMC_Z0_PC
    z0 = low + (high - low) * rho / at
    surface = np.exp(-rho / LMC_SCALE_PC) / (2 * np.pi * LMC_SCALE_PC**2)
    vertical = 1.0 / (2 * z0 * np.cosh(np.minimum(np.abs(height) / z0, 40.0)) ** 2)
    return np.where(rho < LMC_REACH_PC, surface * vertical, 0.0)


@cache
def smc_frame() -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """Core centre, debris centre, line of sight to the debris (pc), and its spread
    across the sky."""
    row = sources.lvdb_cloud("smc")
    core, _, _ = sky_vectors(*SMC_CORE)
    toward, _, _ = sky_vectors(row.ra_deg, row.dec_deg)
    return (
        SMC_DISTANCE_PC * core,
        SMC_DISTANCE_PC * toward,
        toward,
        row.half_light_pc / 1.177,
    )


def smc_shape(x, y, z) -> np.ndarray:
    core, centre, toward, sigma = smc_frame()
    p = np.stack((x, y, z), axis=-1)
    r = np.linalg.norm(p - core, axis=-1)
    a = SMC_CORE_SCALE_PC
    inner = np.exp(-r / a) / (8 * np.pi * a**3)
    q = p - centre
    along = q @ toward
    side2 = np.maximum((q * q).sum(axis=-1) - along * along, 0.0)
    debris = np.exp(-0.5 * (along / SMC_DEPTH_PC) ** 2 - 0.5 * side2 / sigma**2) / (
        (2 * np.pi) ** 1.5 * SMC_DEPTH_PC * sigma * sigma
    )
    return SMC_CORE_SHARE * inner + (1 - SMC_CORE_SHARE) * debris


def shape(name: str, x, y, z) -> np.ndarray:
    return lmc_shape(x, y, z) if name == "lmc" else smc_shape(x, y, z)
