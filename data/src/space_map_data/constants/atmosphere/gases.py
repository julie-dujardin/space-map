"""Optical constants per gas, from primary dispersion measurements.

Refractivity is stored as a dispersion fit so rendering can evaluate any
visible wavelength, not just the three render channels:

    (n - 1) × 1e8 = const + cauchy_b·s² + Σ  b / (c - s²)      s = 1/λ [µm⁻¹]

covering the published fit families (Peck-style Sellmeier, Cauchy). Each fit
applies at its source's reference density (`fit_number_density`); Rayleigh
cross sections are density-independent since (n-1) scales with N.

King correction (depolarisation): F = king_a + king_b·s² + king_c·s⁴, per
Bates 1984 and Sneep & Ubachs 2005 (JQSRT 92, 293). Monatomic gases and
tetrahedral CH₄ are isotropic (F = 1).

Validated in tests/export/test_atmospheres.py against measured values (He et
al. 2021, ACP 21, 14927; Sneep & Ubachs 2005) and, for H₂, the Dalgarno &
Williams 1962 ab initio formula.
"""

from typing import NamedTuple

BOLTZMANN = 1.380649e-23  # J/K, exact (2019 SI)

# Number densities the dispersion fits below are quoted at, molecules/m³.
_N_0C = 2.686780111e25  # Loschmidt, 0 °C / 101.325 kPa (CODATA 2022, exact)
_N_15C = 2.546899e25  # 15 °C / 101.325 kPa (Bodhaine et al. 1999, eq. 24)
_N_20C = 2.503472e25  # 20 °C / 101.325 kPa (ideal gas at CODATA k)


class GasOptics(NamedTuple):
    molar_mass_g_mol: float
    dispersion_const: float
    dispersion_cauchy_b: float
    dispersion_terms: tuple[tuple[float, float], ...]
    fit_number_density: float
    king_a: float
    king_b: float = 0.0
    king_c: float = 0.0

    def refractivity(self, wavelength_m: float) -> float:
        """(n - 1) at the fit's reference density."""
        s2 = 1.0 / (wavelength_m * 1e6) ** 2
        n_minus_1 = self.dispersion_const + self.dispersion_cauchy_b * s2
        for b, c in self.dispersion_terms:
            n_minus_1 += b / (c - s2)
        return n_minus_1 * 1e-8

    def king_factor(self, wavelength_m: float) -> float:
        s2 = 1.0 / (wavelength_m * 1e6) ** 2
        return self.king_a + self.king_b * s2 + self.king_c * s2 * s2


# Molar masses: NIST WebBook. King factors converted from the papers'
# wavenumber forms via s²[µm⁻²] = ν̄²[cm⁻²] × 1e-8.
GAS_OPTICS: dict[str, GasOptics] = {
    # Peck & Khanna 1966 (JOSA 56, 1059), 15 °C form, valid 0.468-2.06 µm.
    # King: Bates 1984 (Planet. Space Sci. 32, 785): F = 1.034 + 3.17e-4/λ².
    "N2": GasOptics(
        molar_mass_g_mol=28.0134,
        dispersion_const=6497.378,
        dispersion_cauchy_b=0.0,
        dispersion_terms=((3.0738649e6, 144.0),),
        fit_number_density=_N_15C,
        king_a=1.034,
        king_b=3.17e-4,
    ),
    # Zhang et al. 2008 (Appl. Opt. 47, 3143; Křen 2011 comment), 20 °C,
    # valid 0.4-1.8 µm — modern visible anchor with unambiguous conditions
    # (Bates 1984's O₂ reference conditions are disputed in the literature).
    # King: Bates 1984: F = 1.096 + 1.385e-3/λ² + 1.448e-4/λ⁴.
    "O2": GasOptics(
        molar_mass_g_mol=31.9988,
        dispersion_const=11814.94,
        dispersion_cauchy_b=0.0,
        dispersion_terms=((9.708931e5, 75.4),),
        fit_number_density=_N_20C,
        king_a=1.096,
        king_b=1.385e-3,
        king_c=1.448e-4,
    ),
    # Bideau-Méhu et al. 1973 (Opt. Commun. 9, 432), 0 °C, valid
    # 0.181-1.695 µm. (The wavenumber restatements of this fit in Sneep &
    # Ubachs 2005 / later papers carry misprinted exponents on the IR term —
    # this is the verified wavelength form.)
    # King: Sneep & Ubachs 2005 fit to Alms et al. 1975: F = 1.1364 + 25.3e-12·ν̄².
    "CO2": GasOptics(
        molar_mass_g_mol=44.0095,
        dispersion_const=0.0,
        dispersion_cauchy_b=0.0,
        dispersion_terms=(
            (6.99100e6, 166.175),
            (1.44720e5, 79.609),
            (6429.41, 56.3064),
            (5213.06, 46.0196),
            (146.847, 0.0584738),
        ),
        fit_number_density=_N_0C,
        king_a=1.1364,
        king_b=2.53e-3,
    ),
    # He et al. 2021 (ACP 21, 14927) BBCES-derived dispersion, 288.15 K,
    # valid 264-671 nm. Preferred over the older Hohm-polarizability fit,
    # which overestimates σ by ~18%. King = 1 (tetrahedral, isotropic).
    "CH4": GasOptics(
        molar_mass_g_mol=16.0425,
        dispersion_const=3603.09,
        dispersion_cauchy_b=0.0,
        dispersion_terms=((4.40362e6, 117.41),),
        fit_number_density=_N_15C,
        king_a=1.0,
    ),
    # Peck & Huang 1977 (JOSA 67, 1550), 0 °C, valid 0.168-1.695 µm.
    # King = 1: no verified primary source for H₂'s small (~2%) anisotropy
    # correction; the derived σ is instead validated against Dalgarno &
    # Williams 1962 (ApJ 136, 690), the standard H₂ Rayleigh source in
    # planetary radiative transfer.
    "H2": GasOptics(
        molar_mass_g_mol=2.01588,
        dispersion_const=0.0,
        dispersion_cauchy_b=0.0,
        dispersion_terms=((1.48956e6, 180.7), (4.9037e5, 92.0)),
        fit_number_density=_N_0C,
        king_a=1.0,
    ),
    # Mansfield & Peck 1969 (JOSA 59, 199), 0 °C, valid 0.480-2.059 µm.
    "He": GasOptics(
        molar_mass_g_mol=4.002602,
        dispersion_const=0.0,
        dispersion_cauchy_b=0.0,
        dispersion_terms=((1.470091e6, 423.98),),
        fit_number_density=_N_0C,
        king_a=1.0,
    ),
    # Peck & Fisher 1964 (JOSA 54, 1362), 15 °C form, valid 0.468-2.06 µm.
    "Ar": GasOptics(
        molar_mass_g_mol=39.948,
        dispersion_const=6432.135,
        dispersion_cauchy_b=0.0,
        dispersion_terms=((2.8606021e6, 144.0),),
        fit_number_density=_N_15C,
        king_a=1.0,
    ),
}
