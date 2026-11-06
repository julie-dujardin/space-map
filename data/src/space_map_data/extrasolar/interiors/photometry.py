"""Teff from B − V, and luminosity from V or from a radius, for the stars
that Gaia gives no Teff or luminosity.

- Casagrande et al. 2010 (A&A 512, A54), Table 4: Teff from B − V and
  [Fe/H] for FGK dwarfs and subgiants, from the infrared flux method.
- Flower 1996 (ApJ 469, 355) with the coefficients that Torres 2010 (AJ 140,
  1158) corrects: Teff from B − V for main-sequence stars, subgiants and
  giants (Torres Table 2), and BC_V from Teff for every class (Torres
  Table 1). Torres gives Mbol⊙ = 4.73 for this BC scale, and says that the
  BCs do not hold for M dwarfs.

Colours and magnitudes are Johnson, as Hipparcos and SIMBAD give them.
"""

import numpy as np

from space_map_data.constants.planets.families import SUN_TEFF

CASAGRANDE_2010 = "casagrande-2010"
FLOWER_1996 = "flower-1996"

# θ = 5040 / Teff = a0 + a1 X + a2 X² + a3 X [Fe/H] + a4 [Fe/H] + a5 [Fe/H]².
CASAGRANDE_COEFFICIENTS = (0.5665, 0.4809, -0.0060, -0.0613, -0.0042, -0.0055)
CASAGRANDE_COLOURS = (0.18, 1.29)
CASAGRANDE_FEH = (-5.0, 0.4)
# The scatter of the stars around the relation, K.
CASAGRANDE_SIGMA = 73.0

# log Teff = Σ c_i (B − V)^i.
FLOWER_TEFF_COEFFICIENTS = (
    3.979145106714099,
    -0.654992268598245,
    1.740690042385095,
    -4.608815154057166,
    6.792599779944473,
    -5.396909891322525,
    2.192970376522490,
    -0.359495739295671,
)
# The B − V range of Flower's Table 3.
FLOWER_COLOURS = (-0.35, 1.80)
# BC_V = Σ c_i (log Teff)^i, under 3.70, from 3.70 to 3.90, over 3.90.
FLOWER_BC_COEFFICIENTS = (
    (
        -0.190537291496456e05,
        0.155144866764412e05,
        -0.421278819301717e04,
        0.381476328422343e03,
    ),
    (
        -0.370510203809015e05,
        0.385672629965804e05,
        -0.150651486316025e05,
        0.261724637119416e04,
        -0.170623810323864e03,
    ),
    (
        -0.118115450538963e06,
        0.137145973583929e06,
        -0.636233812100225e05,
        0.147412923562646e05,
        -0.170587278406872e04,
        0.788731721804990e02,
    ),
)
FLOWER_BC_BREAKS = (3.70, 3.90)
FLOWER_MBOL_SUN = 4.73
# The B − V step of the slope that carries a colour error to Teff.
SLOPE_STEP = 0.01


def _inside(values: np.ndarray, bounds: tuple[float, float]) -> np.ndarray:
    return (values >= bounds[0]) & (values <= bounds[1])


def casagrande_log_teff(b_v: np.ndarray, feh: np.ndarray) -> np.ndarray:
    """log Teff, NaN outside the colour and [Fe/H] ranges of the relation."""
    a0, a1, a2, a3, a4, a5 = CASAGRANDE_COEFFICIENTS
    theta = a0 + a1 * b_v + a2 * b_v**2 + a3 * b_v * feh + a4 * feh + a5 * feh**2
    holds = _inside(b_v, CASAGRANDE_COLOURS) & _inside(feh, CASAGRANDE_FEH)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(holds, np.log10(5040.0 / theta), np.nan)


def flower_log_teff(b_v: np.ndarray) -> np.ndarray:
    """log Teff, NaN outside the colour range of the relation."""
    log_teff = np.polynomial.polynomial.polyval(b_v, FLOWER_TEFF_COEFFICIENTS)
    return np.where(_inside(b_v, FLOWER_COLOURS), log_teff, np.nan)


def flower_bc(log_teff: np.ndarray) -> np.ndarray:
    """BC_V (mag) at log Teff."""
    cool, middle, hot = (
        np.polynomial.polynomial.polyval(log_teff, c) for c in FLOWER_BC_COEFFICIENTS
    )
    low, high = FLOWER_BC_BREAKS
    return np.where(log_teff < low, cool, np.where(log_teff < high, middle, hot))


def slope(log_teff_of, b_v: np.ndarray, *more: np.ndarray) -> np.ndarray:
    """|d log Teff / d(B − V)| of a relation, by a central difference, and by
    a one-sided difference at the ends of the relation's range."""
    half = SLOPE_STEP / 2
    up = log_teff_of(b_v + half, *more)
    middle = log_teff_of(b_v, *more)
    down = log_teff_of(b_v - half, *more)
    central = (up - down) / SLOPE_STEP
    one_sided = np.where(np.isfinite(up), up - middle, middle - down) / half
    return np.abs(np.where(np.isfinite(central), central, one_sided))


def log_l_from_v(
    v_mag: np.ndarray, distance_pc: np.ndarray, a_v: np.ndarray, log_teff: np.ndarray
) -> np.ndarray:
    """log L/L☉ from V, the distance, the extinction and Flower's BC."""
    with np.errstate(invalid="ignore", divide="ignore"):
        absolute = v_mag - 5 * np.log10(distance_pc) + 5 - a_v
    return -0.4 * (absolute + flower_bc(log_teff) - FLOWER_MBOL_SUN)


def log_l_from_radius(radius_sun: np.ndarray, log_teff: np.ndarray) -> np.ndarray:
    """log L/L☉ = log (R/R☉)² (Teff/Teff☉)⁴, the Stefan–Boltzmann law."""
    with np.errstate(invalid="ignore", divide="ignore"):
        return 2 * np.log10(radius_sun) + 4 * (log_teff - np.log10(SUN_TEFF))
