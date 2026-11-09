"""Whether a planet is tidally locked to its star.

The despinning time of Gladman et al. 1996 (Icarus 122, 166), with the moment
of inertia of a uniform sphere, I = 0.4 m R²:

    t_lock = ω a⁶ I Q / (3 G M*² k₂ R⁵)

A despun planet on an eccentric orbit spins pseudo-synchronously (Hut 1981,
A&A 99, 126, eq. 42). It is locked when t_lock is shorter than the age of its
star and its spin is near its mean motion. The catalogue values go in as they
are, estimates too, and an assumed eccentricity is 0.
"""

import math

from space_map_data.constants.physics import G
from space_map_data.constants.planets.families import (
    EARTH_RADII_PER_JUPITER,
    JUPITER_MASS_G,
    JUPITER_RADIUS_CM,
)

AU_M = 1.495_978_707e11
SUN_KG = 1.988_47e30
JUPITER_KG = JUPITER_MASS_G / 1000
JUPITER_M = JUPITER_RADIUS_CM / 100
YEAR_S = 365.25 * 86_400

# The spin at formation, 12 h, as Gladman et al. take it.
INITIAL_SPIN = 2 * math.pi / (12 * 3600)
# I / (m R²) of a uniform sphere, as Gladman et al. take it.
INERTIA_FACTOR = 0.4
# Earth radii. Most planets above it hold an envelope of gas (Rogers 2015,
# ApJ 801, 41).
ROCKY_RADIUS = 1.6
# Q and k₂ of a rocky planet, Gladman et al.'s values for a solid body.
ROCKY_Q = 100
ROCKY_K2 = 0.3
# Q and k₂ of a planet with an envelope: Jupiter's Q is 10⁵ to 10⁶
# (Goldreich & Soter 1966), and its k₂ is near 0.5.
GAS_Q = 1e5
GAS_K2 = 0.5
# Years. The age of a star that the catalogue gives no age for: a young field
# star, so only a fast lock counts.
DEFAULT_AGE = 1e9
# The largest |Ω_ps / n - 1| of a locked planet (about e < 0.09). Above it the
# star drifts across the sky of the planet.
SYNCHRONOUS_TOLERANCE = 0.05


def lock_time(
    semi_major_axis: float, mass: float, radius: float, star_mass: float
) -> float:
    """The despinning time in years. Units of the planets table: AU, Jupiter
    masses and radii, solar masses."""
    rocky = radius * EARTH_RADII_PER_JUPITER < ROCKY_RADIUS
    q, k2 = (ROCKY_Q, ROCKY_K2) if rocky else (GAS_Q, GAS_K2)
    m, r = mass * JUPITER_KG, radius * JUPITER_M
    a, star = semi_major_axis * AU_M, star_mass * SUN_KG
    inertia = INERTIA_FACTOR * m * r**2
    seconds = INITIAL_SPIN * a**6 * inertia * q / (3 * G * star**2 * k2 * r**5)
    return seconds / YEAR_S


def pseudo_synchronous_ratio(eccentricity: float) -> float:
    """Ω_ps / n, the spin of a despun planet over its mean motion (Hut 1981,
    eq. 42)."""
    e2 = eccentricity**2
    spin = 1 + 15 / 2 * e2 + 45 / 8 * e2**2 + 5 / 16 * e2**3
    return spin / ((1 + 3 * e2 + 3 / 8 * e2**2) * (1 - e2) ** 1.5)


def tidally_locked(values: dict, host: dict) -> bool | None:
    """Whether the planet of a system file record is locked: `values` are the
    planet's, `host` is its host record. The star's mass is that of the
    planet's fit, else of the host. None when a value is missing or the
    eccentricity is outside [0, 1)."""
    star_mass = values.get("star_mass") or host["mass"]
    a, mass, radius = (values.get(n) for n in ("semi_major_axis", "mass", "radius"))
    eccentricity = values.get("eccentricity") or 0.0
    if not (a and mass and radius and star_mass) or not 0 <= eccentricity < 1:
        return None
    age = host["age"] * 1e9 if host["age"] else DEFAULT_AGE
    if lock_time(a, mass, radius, star_mass) >= age:
        return False
    return abs(pseudo_synchronous_ratio(eccentricity) - 1) <= SYNCHRONOUS_TOLERANCE
