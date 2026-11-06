"""Bands and colours of integrated light, on the client's star colour.

A population takes one BP - RP, and the client's star colour (`glow.colour`) gives
its display colour, so the model's light has the units and colours of the catalogue
grid. The relations are stellar ones (Riello et al. 2021, Table C.2). Integrated light
is a mix of stars, so a colour index read through them is an approximation, and two
indices of one population can give two values of BP - RP.
"""

import numpy as np

from space_map_data.glow import colour

# Willmer 2018, Table 3: the Sun's absolute magnitudes. Johnson and 2MASS in Vega,
# SDSS in AB.
SUN_V = 4.81
SUN_B = 5.44
SUN_SDSS_G = 5.11
SUN_SDSS_R = 4.65
SUN_H = 3.32

# Riello et al. 2021, Table C.2, coefficients of ascending powers of BP - RP.
G_MINUS_V = (-0.02704, 0.01424, -0.2156, 0.01426)
G_MINUS_R = (-0.09837, 0.08592, 0.1907, -0.1701, 0.02263)
G_MINUS_SDSS_G = (0.2199, -0.6365, -0.1548, 0.0064)
G_MINUS_H = (-0.1048, 2.011, -0.1758)
# The same table, G - V in powers of B - V.
G_MINUS_V_OF_B_V = (-0.04749, -0.0124, -0.2901, 0.02008)

BP_RP_RANGE = (-0.3, 3.0)
_GRID = np.linspace(*BP_RP_RANGE, 3301)


def _poly(coefficients: tuple[float, ...], x):
    return np.polynomial.polynomial.polyval(x, coefficients)


def gaia_minus_v(bp_rp):
    return _poly(G_MINUS_V, bp_rp)


def gaia_minus_r(bp_rp):
    return _poly(G_MINUS_R, bp_rp)


def gaia_minus_g(bp_rp):
    return _poly(G_MINUS_SDSS_G, bp_rp)


def b_minus_v(bp_rp):
    """B - V, by inverting G - V as a function of B - V. That relation peaks near
    B - V = 0, so bluer light reads 0: B stars of BP - RP under about 0.35."""
    target = np.asarray(gaia_minus_v(bp_rp))
    b_v = np.linspace(0.0, 2.5, 2501)
    # G - V falls with B - V over this range.
    return np.interp(-target, -_poly(G_MINUS_V_OF_B_V, b_v), b_v)


def g_minus_r(bp_rp):
    """SDSS g - r."""
    return gaia_minus_r(bp_rp) - gaia_minus_g(bp_rp)


def r_minus_h(bp_rp):
    return _poly(G_MINUS_H, bp_rp) - gaia_minus_r(bp_rp)


def _inverse(function, value):
    """BP - RP where a rising or falling `function` of it takes `value`."""
    y = function(_GRID)
    order = np.argsort(y)
    return np.interp(value, y[order], _GRID[order])


def bp_rp_of_b_v(b_v):
    return _inverse(gaia_minus_v, _poly(G_MINUS_V_OF_B_V, np.asarray(b_v)))


def bp_rp_of_r_h(r_h):
    return _inverse(r_minus_h, r_h)


def display(bp_rp) -> np.ndarray:
    """The client's star colour, largest channel 1, shape (..., 3)."""
    return colour.star_colours(np.atleast_1d(np.asarray(bp_rp, float)))


def tint(rgb: np.ndarray) -> np.ndarray:
    """B / (R + B), the measure of a colour along the star locus."""
    rgb = np.asarray(rgb, float)
    return rgb[..., 2] / (rgb[..., 0] + rgb[..., 2])


def bp_rp_of_display(rgb: np.ndarray) -> np.ndarray:
    """The BP - RP whose star colour has the tint of `rgb`."""
    # The star colour stops changing outside its table.
    grid = _GRID[(_GRID >= colour.LUT_LOW) & (_GRID <= colour.LUT_HIGH)]
    return np.interp(-tint(rgb), -tint(display(grid)), grid)


def band_magnitudes(m_g, bp_rp) -> dict[str, np.ndarray]:
    """Absolute magnitudes in V, B, SDSS g and r of light with G magnitude `m_g`."""
    m_v = m_g - gaia_minus_v(bp_rp)
    m_r = m_g - gaia_minus_r(bp_rp)
    return {
        "G": np.asarray(m_g),
        "V": m_v,
        "B": m_v + b_minus_v(bp_rp),
        "r": m_r,
        "g": m_r + g_minus_r(bp_rp),
    }
