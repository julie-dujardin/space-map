"""Rayleigh scattering coefficients from gas optical constants.

Per-molecule cross section (King-corrected Lorentz-Lorenz form):

    sigma(lambda) = 24 pi^3 / (lambda^4 N_fit^2) * ((n^2-1)/(n^2+2))^2 * F_king

sigma is density-independent since (n-1) scales with N. Mixture coefficient:

    beta(lambda) = N_ref * sum_i f_i * sigma_i(lambda)

Weighted by cross section, not refractivity — squaring a mixed refractivity
would misweight strong trace scatterers like CO2 in air.
"""

import math

from space_map_data.constants.atmosphere.gases import GAS_OPTICS

BOLTZMANN = 1.380649e-23  # J/K, exact (2019 SI)


def number_density(pressure_pa: float, temperature_k: float) -> float:
    """Ideal-gas number density in molecules/m^3."""
    return pressure_pa / (BOLTZMANN * temperature_k)


def rayleigh_cross_section(gas: str, wavelength_m: float) -> float:
    """Per-molecule Rayleigh cross section, m^2."""
    optics = GAS_OPTICS[gas]
    n = 1.0 + optics.refractivity(wavelength_m)
    lorentz = (n * n - 1.0) / (n * n + 2.0)
    return (
        24.0
        * math.pi**3
        / (wavelength_m**4 * optics.fit_number_density**2)
        * lorentz**2
        * optics.king_factor(wavelength_m)
    )


def rayleigh_beta_per_m(
    composition: dict[str, float],
    pressure_pa: float,
    temperature_k: float,
    wavelength_m: float,
) -> float:
    """Volume scattering coefficient (1/m) for a gas mixture at (P, T).

    Fractions are renormalised so a truncated composition list doesn't
    underestimate beta.
    """
    total = sum(composition.values())
    sigma = sum(
        fraction / total * rayleigh_cross_section(gas, wavelength_m)
        for gas, fraction in composition.items()
    )
    return number_density(pressure_pa, temperature_k) * sigma


def mixture_refractivity(
    composition: dict[str, float],
    pressure_pa: float,
    temperature_k: float,
    wavelength_m: float,
) -> float:
    """(n - 1) of a gas mixture at (P, T). Refractivities scale linearly with
    number density and add by partial density (Lorentz-Lorenz at n ≈ 1)."""
    total = sum(composition.values())
    n_ref = number_density(pressure_pa, temperature_k)
    return sum(
        fraction
        / total
        * GAS_OPTICS[gas].refractivity(wavelength_m)
        * (n_ref / GAS_OPTICS[gas].fit_number_density)
        for gas, fraction in composition.items()
    )


def scale_height_km(
    mean_molar_mass_g_mol: float, temperature_k: float, gravity_m_s2: float
) -> float:
    """Isothermal pressure scale height H = kT / (m g), in km."""
    avogadro = 6.02214076e23  # 1/mol, exact (2019 SI)
    molecule_mass_kg = mean_molar_mass_g_mol * 1e-3 / avogadro
    return BOLTZMANN * temperature_k / (molecule_mass_kg * gravity_m_s2) / 1000.0


def mean_molar_mass_g_mol(composition: dict[str, float]) -> float:
    """Number-fraction-weighted molar mass of a mixture, g/mol."""
    total = sum(composition.values())
    return sum(
        fraction / total * GAS_OPTICS[gas].molar_mass_g_mol
        for gas, fraction in composition.items()
    )
