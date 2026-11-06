"""The emission lines in the stars' display units.

A star of apparent G = 0 has display flux 1 times its colour, the colour in linear
sRGB with its largest channel at 1 (`glow.colour`). A line takes the same rule: its
G flux from its own wavelength through the Gaia DR3 G response, its colour from the
CIE 1931 2 deg observer through the matrix and the clip of `glow.colour`.

Lines, intrinsic, case B at 10^4 K:
- H-alpha 6562.8 A, the unit.
- [N II] 6583.5 A at 0.25 of H-alpha, the value of classical H II regions (Haffner
  et al. 2009, Fig. 2), and [N II] 6548.0 A at a third of it.
- H-beta 4861.3 A at H-alpha / 2.87 (Osterbrock & Ferland 2006, as Mascoop et al.
  2021 eq. 6 take it).
[O III] 5007 A is left out: its ratio to H-beta spans more than ten times between
the diffuse gas and bright regions, so no one value holds.

The red channel holds only the 656 nm lines and the green and blue channels only
H-beta, so a K per channel dims each line at its own wavelength.
"""

import numpy as np
import numpy.typing as npt

H_PLANCK = 6.62607015e-34
C_LIGHT = 2.99792458e8
PC_M = 3.0856775814913673e16
PC_CM = PC_M * 100.0
HALPHA_M = 6562.80e-10
# Energy of one H-alpha photon, J.
HALPHA_PHOTON_J = H_PLANCK * C_LIGHT / HALPHA_M

# Display flux of 1 erg s^-1 cm^-2 in a line: lambda S(lambda) / (int lambda S
# dlambda) / F_lambda(Vega), with the SVO GAIA/GAIA3.G response and its Vega zero
# point of 3228.7465 Jy at 6217.59 A (2.50386e-9 erg s^-1 cm^-2 A^-1).
G_PER_CGS = {"halpha": 9.271303e4, "nii_6584": 9.305623e4, "nii_6548": 9.248748e4,
             "hbeta": 6.039621e4}  # fmt: skip
# ZGR23 extinction at the line over A0 at 550 nm.
K_LINE = {"halpha": 0.7960, "nii_6584": 0.7918, "nii_6548": 0.7990, "hbeta": 1.2237}
# Energy flux of each line over H-alpha.
RATIO = {"halpha": 1.0, "nii_6584": 0.25, "nii_6548": 0.25 / 3.0, "hbeta": 1 / 2.87}

# CIE 1931 2 deg colour matching values at the line (CVRL table, linear between 1 nm
# rows), and the matrix of `glow.colour.planckian_rgb`.
_XYZ = {"red": (0.203968, 0.075918, 0.0), "hbeta": (0.051137, 0.177194, 0.578180)}
_XYZ_TO_RGB = np.array(
    (
        (3.2404542, -1.5371385, -0.4985314),
        (-0.969266, 1.8760108, 0.041556),
        (0.0556434, -0.2040259, 1.0572252),
    )
)


def line_rgb(xyz: tuple[float, float, float]) -> np.ndarray:
    """Linear sRGB of a line, negative channels clipped, the largest at 1."""
    rgb = np.maximum(_XYZ_TO_RGB @ np.array(xyz), 0.0)
    return rgb / rgb.max()


RED_RGB = line_rgb(_XYZ["red"])
HBETA_RGB = line_rgb(_XYZ["hbeta"])


def _channels() -> tuple[np.ndarray, np.ndarray]:
    """Display flux per channel of all lines, per erg s^-1 cm^-2 of H-alpha, and the
    K of each channel."""
    red = sum(RATIO[n] * G_PER_CGS[n] for n in ("halpha", "nii_6584", "nii_6548"))
    k_red = (
        sum(
            RATIO[n] * G_PER_CGS[n] * K_LINE[n]
            for n in ("halpha", "nii_6584", "nii_6548")
        )
        / red
    )
    blue = RATIO["hbeta"] * G_PER_CGS["hbeta"]
    flux = red * RED_RGB + blue * HBETA_RGB
    return flux, np.array((k_red, K_LINE["hbeta"], K_LINE["hbeta"]))


FLUX_PER_HALPHA, K_EMISSION = _channels()
# The colour of the emission, rows summing to 1, and R + G + B per unit of H-alpha.
COLOUR = FLUX_PER_HALPHA / FLUX_PER_HALPHA.sum()
TOTAL_PER_HALPHA = float(FLUX_PER_HALPHA.sum())
# Flux at 10 pc per erg s^-1 of luminosity.
AT_TEN_PC = 1.0 / (4 * np.pi * (10.0 * PC_CM) ** 2)


def emissivity_to_display(w_per_m3: npt.ArrayLike) -> np.ndarray:
    """H-alpha emissivity (W m^-3) to the stored unit: R + G + B display flux of
    every line at 10 pc, per pc^3."""
    erg_per_s = np.asarray(w_per_m3) * 1e7 * PC_M**3
    return erg_per_s * AT_TEN_PC * TOTAL_PER_HALPHA


def display_to_emissivity(display: npt.ArrayLike) -> np.ndarray:
    """The inverse of `emissivity_to_display`."""
    return np.asarray(display) / (AT_TEN_PC * TOTAL_PER_HALPHA * 1e7 * PC_M**3)


def luminosity_to_display(erg_per_s: npt.ArrayLike) -> np.ndarray:
    """An H-alpha luminosity (erg/s) to R + G + B display flux of all lines at 10 pc."""
    return np.asarray(erg_per_s) * AT_TEN_PC * TOTAL_PER_HALPHA


def column_to_rayleigh(w_per_m3_pc: npt.ArrayLike) -> np.ndarray:
    """A line integral of H-alpha emissivity (W m^-3 pc) to rayleighs."""
    photons = np.asarray(w_per_m3_pc) * PC_M / (4 * np.pi) / HALPHA_PHOTON_J
    return photons * 4 * np.pi / 1e10
