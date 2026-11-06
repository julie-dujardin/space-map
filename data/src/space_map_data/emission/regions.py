"""The far H II regions: the WISE Catalog of Galactic H II Regions V3.0, the rows
with a distance, outside McCallum's cube.

The intrinsic H-alpha luminosity of a region comes from what the catalogue holds, in
this order:
1. `radio`: the 1.4 GHz flux density (VGPS and MAGPIS, their mean where both, as
   Makai et al. 2017 combine them) to the Lyman continuum rate by Mascoop et al.
   2021 eq. 5 (Rubin 1968, T_e = 10^4 K), then H-alpha under case B (eq. 6).
2. `infrared`: the 24 or 22 um flux density, else 12 um, else 8 um, to the radio
   flux density by the fits of Makai et al. 2017 Table 2 (all regions), then as 1.
3. `size`: the mean rate at the region's physical radius: a fit of log rate on log
   radius over the regions of 1, times the lognormal mean `exp((sigma ln 10)^2 / 2)`
   of the fit's scatter sigma, so the sum over these regions is not biased low. An
   estimate: the scatter is about 0.55 dex, and the largest complexes fall below it.
Radio and infrared light pass through the dust, so these luminosities are intrinsic.

Each region is a Gaussian ball with sigma half the catalogue radius.
"""

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from space_map_data.emission import lines, sky, sources

# Distances from a cited paper over the catalogue's, by WISE name, kpc. W40 (S64)
# has the far kinematic distance in V3.0, 14.5 kpc at b = +3.5 deg, which made it
# the brightest region of the catalogue.
DISTANCE_OVERRIDES = {
    "G028.746+03.458": (0.436, "Ortiz-Leon et al. 2017: VLBA, Serpens/W40 complex"),
}
# McCallum's cube holds the gas to this distance, so regions inside it are dropped.
LOCAL_REACH_PC = 1250.0
SIGMA_OF_RADIUS = 0.5
# Mascoop et al. 2021 eq. 5 at 1.4 GHz and T_e = 10^4 K: N_ly per (nu L_nu / erg/s).
FREQUENCY_HZ = 1.4e9
ELECTRON_TEMPERATURE_K = 1e4
RUBIN = 5.01e26 * ELECTRON_TEMPERATURE_K**-0.45 * FREQUENCY_HZ**-0.9
# Case B at 10^4 K (Osterbrock & Ferland 2006, as Mascoop et al. 2021 take it):
# effective H-beta and case B coefficients, and the H-alpha / H-beta ratio.
ALPHA_HBETA = 3.03e-14
ALPHA_B = 2.59e-13
HALPHA_OVER_HBETA = 2.87
HBETA_M = 4861.33e-10
HALPHA_PER_PHOTON_ERG = (
    ALPHA_HBETA
    / ALPHA_B
    * HALPHA_OVER_HBETA
    * lines.H_PLANCK
    * lines.C_LIGHT
    / HBETA_M
    * 1e7
)
# Makai et al. 2017 Table 2, all regions: S_IR = A S_radio^alpha, Jy.
INFRARED_FITS = {
    "24um": (82.188, 0.822),
    "12um": (34.450, 0.815),
    "8um": (30.573, 0.809),
}
SOURCES = ("radio", "infrared", "size")


@dataclass(frozen=True)
class Regions:
    names: list[str]
    # Nest axes, pc from the Sun.
    position: np.ndarray
    sigma_pc: np.ndarray
    # Lyman continuum rate, s^-1, and the source of each, an index into SOURCES.
    rate: np.ndarray
    source: np.ndarray
    # H-alpha luminosity, erg/s, and R + G + B display flux of all lines at 10 pc.
    halpha_erg_s: np.ndarray
    display: np.ndarray
    distance_pc: np.ndarray
    l_deg: np.ndarray
    b_deg: np.ndarray


def galactic_vector(l_deg: np.ndarray, b_deg: np.ndarray) -> np.ndarray:
    lam, beta = np.radians(l_deg), np.radians(b_deg)
    return np.column_stack(
        (np.cos(beta) * np.cos(lam), np.cos(beta) * np.sin(lam), np.sin(beta))
    )


def radio_flux(row: sources.WiseRow) -> float:
    known = [f for f in (row.vgps, row.magpis) if np.isfinite(f) and f > 0]
    return float(np.mean(known)) if known else np.nan


def infrared_radio_flux(row: sources.WiseRow) -> float:
    """The radio flux density that the infrared one gives, by Makai's fits."""
    choices = (
        ("24um", row.mipsgal),
        ("24um", row.wise4),
        ("12um", row.wise3),
        ("8um", row.glimpse),
    )
    for band, flux in choices:
        if np.isfinite(flux) and flux > 0:
            a, alpha = INFRARED_FITS[band]
            return float((flux / a) ** (1 / alpha))
    return np.nan


def rate_of_radio(flux_jy: npt.ArrayLike, distance_kpc: npt.ArrayLike) -> np.ndarray:
    """Mascoop et al. 2021 eq. 4 and 5."""
    d_cm = np.asarray(distance_kpc) * 1e3 * lines.PC_CM
    nu_l_nu = 4 * np.pi * 1e-23 * np.asarray(flux_jy) * d_cm**2 * FREQUENCY_HZ
    return RUBIN * nu_l_nu


def size_fit(radius_pc: np.ndarray, rate: np.ndarray) -> tuple[float, float, float]:
    """log10 rate = slope log10 radius + offset by least squares, and the scatter."""
    x, y = np.log10(radius_pc), np.log10(rate)
    slope, offset = np.polyfit(x, y, 1)
    return float(slope), float(offset), float(np.std(y - (slope * x + offset)))


def lognormal_mean(scatter_dex: float) -> float:
    """The mean over the median of a lognormal of `scatter_dex`."""
    return float(np.exp((scatter_dex * np.log(10.0)) ** 2 / 2))


def size_rate(
    radius_pc: np.ndarray, slope: float, offset: float, scatter_dex: float
) -> np.ndarray:
    """The mean rate at a radius under the fit."""
    return 10.0 ** (slope * np.log10(radius_pc) + offset) * lognormal_mean(scatter_dex)


def load(reach_pc: float = LOCAL_REACH_PC) -> tuple[Regions, dict]:
    """The regions past `reach_pc`, and a summary of what was dropped and fitted."""
    rows = sources.wise_rows()
    distance = np.array(
        [DISTANCE_OVERRIDES.get(r.name, (r.distance_kpc,))[0] for r in rows]
    )
    radius_pc = np.array([r.radius_arcsec for r in rows]) / 206264.806 * distance * 1e3
    radio = np.array([radio_flux(r) for r in rows])
    infrared = np.array([infrared_radio_flux(r) for r in rows])
    source = np.where(np.isfinite(radio), 0, np.where(np.isfinite(infrared), 1, 2))
    flux = np.where(source == 0, radio, infrared)
    rate = rate_of_radio(flux, distance)
    measured = source == 0
    slope, offset, scatter = size_fit(radius_pc[measured], rate[measured])
    sized = source == 2
    rate[sized] = size_rate(radius_pc[sized], slope, offset, scatter)
    halpha = rate * HALPHA_PER_PHOTON_ERG
    l_deg = np.array([r.l_deg for r in rows])
    b_deg = np.array([r.b_deg for r in rows])
    position = galactic_vector(l_deg, b_deg) * distance[:, None] * 1e3
    kept = distance * 1e3 >= reach_pc
    summary = {
        "rows_with_distance": len(rows),
        "dropped_inside_cube": int((~kept).sum()),
        "dropped_light_share": float(halpha[~kept].sum() / halpha.sum()),
        "used": int(kept.sum()),
        "by_source": {
            name: int((kept & (source == i)).sum()) for i, name in enumerate(SOURCES)
        },
        "light_share_by_source": {
            name: float(halpha[kept & (source == i)].sum() / halpha[kept].sum())
            for i, name in enumerate(SOURCES)
        },
        "size_fit": {
            "slope": slope,
            "offset": offset,
            "scatter_dex": scatter,
            "mean_over_median": lognormal_mean(scatter),
        },
        "distance_overrides": {
            name: {"kpc": kpc, "source": source}
            for name, (kpc, source) in DISTANCE_OVERRIDES.items()
        },
    }
    regions = Regions(
        [r.name for r, k in zip(rows, kept, strict=True) if k],
        position[kept],
        radius_pc[kept] * SIGMA_OF_RADIUS,
        rate[kept],
        source[kept],
        halpha[kept],
        lines.luminosity_to_display(halpha[kept]),
        distance[kept] * 1e3,
        l_deg[kept],
        b_deg[kept],
    )
    return regions, summary


def paint(regions: Regions, seen_erg_s: np.ndarray, nside: int) -> np.ndarray:
    """The regions on a sky from the Sun, in rayleighs of H-alpha: each a Gaussian of
    sigma / distance, its flux the `seen_erg_s` it sends through the dust."""
    flux = seen_erg_s / (4 * np.pi * (regions.distance_pc * lines.PC_CM) ** 2)
    photons = flux / (lines.HALPHA_PHOTON_J * 1e7)
    axes = regions.position / regions.distance_pc[:, None]
    sigma = regions.sigma_pc / regions.distance_pc
    painted = sky.paint(axes, sigma, photons[:, None], nside)[:, 0]
    # Photons s^-1 cm^-2 sr^-1 to rayleighs.
    return painted * 4 * np.pi / 1e6
