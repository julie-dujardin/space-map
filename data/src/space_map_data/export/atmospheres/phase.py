"""Per-channel aerosol phase-function LUTs.

Spherical particles use Mie theory over a log-normal size distribution;
irregular particles (Mars dust, Titan aggregates) use double-Henyey-Greenstein
fits instead, since sphere-based Mie theory can't represent them.

Layout matches the frontend contract (surface/atmosphere.ts): 3 blocks of
PHASE_N floats (R,G,B), sampled at theta = pi*(i/(N-1))^2 to concentrate
samples on the forward peak, each normalised to integrate to 1 over the sphere.
"""

import math

import numpy as np

from space_map_data.constants.atmosphere.aerosols import (
    DoubleHenyeyGreenstein,
    LogNormalMie,
)

PHASE_N = 128
# Dense polar grid the physics is evaluated on before warping down to PHASE_N.
_DENSE = 6000

_theta = np.linspace(0.0, math.pi, _DENSE)
_mu = np.cos(_theta)
_theta_warp = math.pi * (np.arange(PHASE_N) / (PHASE_N - 1)) ** 2


def _finish(phase: np.ndarray) -> tuple[list[float], float]:
    """Normalise over the sphere, resample onto the warped grid, return
    (lut_channel, asymmetry_g)."""
    norm = 2.0 * math.pi * np.trapezoid(phase * np.sin(_theta), _theta)
    phase = phase / norm
    g = 2.0 * math.pi * np.trapezoid(phase * _mu * np.sin(_theta), _theta)
    lut = np.interp(_theta_warp, _theta, phase)
    return [float(v) for v in lut], float(g)


def _mie_phase(mode: LogNormalMie, wavelength_um: float) -> np.ndarray:
    import miepython

    # sigma from log-normal effective variance; radii sampled +-3 sigma in log
    # space, weighted by n(r)*Qsca*r^2 so the average matches what a photon meets.
    sigma = math.sqrt(math.log(1.0 + mode.effective_variance))
    log_rg = math.log(mode.effective_radius_um)
    radii = np.exp(np.linspace(log_rg - 3 * sigma, log_rg + 3 * sigma, 41))
    number = np.exp(-0.5 * ((np.log(radii) - log_rg) / sigma) ** 2) / radii

    m = complex(mode.refractive_index_real, -mode.refractive_index_imag)
    accum = np.zeros(_DENSE)
    weight_sum = 0.0
    for radius, n_r in zip(radii, number):
        x = 2.0 * math.pi * radius / wavelength_um
        intensity = miepython.i_unpolarized(m, x, _mu, norm="one")
        q_sca = miepython.efficiencies_mx(m, x)[1]
        weight = n_r * q_sca * radius * radius
        accum += weight * intensity
        weight_sum += weight
    return accum / weight_sum


def _hg(g: float) -> np.ndarray:
    return (
        (1.0 / (4.0 * math.pi)) * (1.0 - g * g) / (1.0 + g * g - 2.0 * g * _mu) ** 1.5
    )


def _dhg_phase(fit: DoubleHenyeyGreenstein) -> np.ndarray:
    return fit.forward_weight * _hg(fit.g_forward) + (1.0 - fit.forward_weight) * _hg(
        fit.g_back
    )


def build_phase_lut(
    aerosol: LogNormalMie | dict[str, DoubleHenyeyGreenstein],
    wavelengths_m: dict[str, float],
) -> tuple[list[float], dict[str, float]]:
    """Build one 3*PHASE_N LUT (R,G,B blocks) for an aerosol.

    Returns (flat_lut, asymmetry_g) — g is for reference checks only, not shipped.
    """
    lut: list[float] = []
    asymmetry: dict[str, float] = {}
    for channel in ("r", "g", "b"):
        if isinstance(aerosol, LogNormalMie):
            # Mie works in µm alongside the particle radii; passing metres
            # produces size parameters of ~1e7 and a solver that never returns.
            dense = _mie_phase(aerosol, wavelengths_m[channel] * 1e6)
        else:
            dense = _dhg_phase(aerosol[channel])
        channel_lut, g = _finish(dense)
        lut.extend(round(v, 5) for v in channel_lut)
        asymmetry[channel] = g
    return lut, asymmetry
