"""Spectral absorption data for future many-wavelength rendering.

Gas Rayleigh spectra need no tables — evaluate `gases.GAS_OPTICS`'s dispersion
fits at any wavelength. This module holds what dispersion can't give: band
absorption cross sections.

Known gap: Karkoschka's 300-1000 nm CH₄ coefficients (what makes Uranus/
Neptune teal — Karkoschka 1994, Icarus 111, 174; Karkoschka & Tomasko 2010,
Icarus 205, 674) have no verified machine-readable copy; tabulations circulate
inside RT codes (NEMESIS), and Irwin's band files cover only 1-5 µm. Extract
from the 1994 table when the giants go physical — the render carries their
colour in the surface textures meanwhile.
"""

# Ozone Chappuis-band cross sections, cm² molecule⁻¹ at 293 K on a 10 nm
# grid (±1 nm means), reduced from the Serdyuchenko/Gorshelev dataset
# (Gorshelev et al. 2014, AMT 7, 609; data doi:10.5281/zenodo.5793206,
# CC-BY 4.0). Temperature dependence in the Chappuis band is < 2%.
# The AbsorberBand triplet in bodies.py samples this at 680/550/440 nm.
OZONE_CROSS_SECTIONS_CM2: tuple[tuple[int, float], ...] = (
    (400, 1.106e-23),
    (410, 2.718e-23),
    (420, 3.721e-23),
    (430, 6.441e-23),
    (440, 1.348e-22),
    (450, 1.872e-22),
    (460, 3.730e-22),
    (470, 4.158e-22),
    (480, 7.457e-22),
    (490, 8.027e-22),
    (500, 1.179e-21),
    (510, 1.538e-21),
    (520, 1.787e-21),
    (530, 2.606e-21),
    (540, 2.861e-21),
    (550, 3.287e-21),
    (560, 3.858e-21),
    (570, 4.567e-21),
    (580, 4.542e-21),
    (590, 4.360e-21),
    (600, 5.042e-21),
    (610, 4.683e-21),
    (620, 3.969e-21),
    (630, 3.484e-21),
    (640, 2.937e-21),
    (650, 2.465e-21),
    (660, 2.076e-21),
    (670, 1.690e-21),
    (680, 1.361e-21),
    (690, 1.120e-21),
    (700, 8.613e-22),
)
