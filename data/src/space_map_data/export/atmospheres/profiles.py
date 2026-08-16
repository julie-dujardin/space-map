"""Vertical-structure derivations: layered Mie density LUTs (Venus, Titan) and the
Mars seasonal table.

The shader samples a PROFILE_N-texel profile over [0, top_altitude_km],
column-normalised to the exponential's β·H so disc opacity matches across
tiers; bodies without a profile keep the single-exponential fallback.
"""

import math

from space_map_data.constants.atmosphere.aerosols import AEROSOLS
from space_map_data.constants.atmosphere.bodies import ATMOSPHERE_BODIES
from space_map_data.constants.atmosphere.layers import (
    MARS_CONRATH_NU_CLEAR,
    MARS_CONRATH_NU_DUSTY,
    TITAN_DETACHED_LAYER_KM,
)
from space_map_data.constants.atmosphere.seasonal import (
    MARS_DUST_TAU_CLEAR,
    MARS_DUST_TAU_VIS,
    MARS_PRESSURE_MBAR,
    MARS_SEASON_LS_DEG,
)
from space_map_data.export.atmospheres.conditions import render_conditions
from space_map_data.export.atmospheres.rayleigh import (
    mean_molar_mass_g_mol,
    scale_height_km,
)

PROFILE_N = 128

# Bodies whose profile needs more altitude than the scale-height shell top
# gives; export raises top_altitude_km to at least this (Titan's layer ~500 km).
MIN_PROFILE_TOP_KM: dict[str, float] = {"naif-606": 600.0}


def _venus_density(h_km: float) -> float:
    """Mie density above the ~70 km cloud deck the texture shows (h = 0).

    Upper haze: H = 4.4 km exponential (Titov et al. 2018). Detached layers at
    80-85 km appear in ~60% of high-resolution profiles, modelled as a
    half-strength bump. Decks below the datum aren't modelled — the rendered
    deck is already opaque.
    """
    base = math.exp(-h_km / 4.4)
    detached = 0.029 * math.exp(-(((h_km - 12.5) / 1.5) ** 2) / 2.0)
    return base + detached


def _titan_density(h_km: float) -> float:
    """Mie density for Titan's haze (h = 0 at the surface).

    Doose et al. 2016 structure: near-linear optical depth below ~100 km with
    a condensate increase under 55 km, then ~50 km scale height above.
    Detached layer at ~500 km (Lavvas et al. 2009 / West et al. 2011) with the
    observed gap below it.
    """
    if h_km < 55.0:
        base = 1.0 - 0.33 * (h_km / 55.0)
    elif h_km < 100.0:
        base = 0.67
    else:
        base = 0.67 * math.exp(-(h_km - 100.0) / 50.0)
    lo, hi = TITAN_DETACHED_LAYER_KM
    center = (lo + hi) / 2.0
    # The clearing between main haze and detached layer must cut deep enough
    # that the layer reads as a local maximum over the decaying background.
    gap = 1.0 - 0.75 * math.exp(-(((h_km - (center - 45.0)) / 20.0) ** 2) / 2.0)
    layer = 4.5e-4 * math.exp(-(((h_km - center) / 18.0) ** 2) / 2.0)
    return base * gap + layer


_PROFILE_BUILDERS = {"naif-299": _venus_density, "naif-606": _titan_density}


def build_mie_profile(object_id: str, top_km: float) -> list[float] | None:
    """PROFILE_N Mie densities over [0, top_km]; None for single-exponential bodies.

    Normalised to the exponential's column (β·H, what the cited optical depths
    anchor) so disc opacity matches across tiers. Last texel forced to 0 so the
    shell has no density at its silhouette, matching the shader's shifted
    exponentials.
    """
    builder = _PROFILE_BUILDERS.get(object_id)
    if builder is None:
        return None
    body = ATMOSPHERE_BODIES[object_id]
    mie_h_km = AEROSOLS[body.aerosol].scale_height_km
    profile = [builder(top_km * i / (PROFILE_N - 1)) for i in range(PROFILE_N)]
    profile[-1] = 0.0
    dh = top_km / (PROFILE_N - 1)
    column = sum(profile) * dh - 0.5 * dh * (profile[0] + profile[-1])
    return [v * mie_h_km / column for v in profile]


def conrath_dust_scale_height_km(nu: float, gas_h_km: float) -> float:
    """Density-weighted mean altitude of the Conrath 1975 dust profile
    q(p) = q0·exp(ν·(1 − p0/p)) over an isothermal gas column of scale height
    `gas_h_km`. ν → 0 recovers well-mixed dust (H_eff → gas H); ν = 0.3 confines
    it low."""
    steps = 4000
    z_top = 12.0 * gas_h_km
    dz = z_top / steps
    total = 0.0
    weighted = 0.0
    for i in range(steps):
        z = (i + 0.5) * dz
        density = math.exp(-z / gas_h_km) * math.exp(
            nu * (1.0 - math.exp(z / gas_h_km))
        )
        total += density
        weighted += z * density
    return weighted / total


def mars_seasonal_table() -> dict:
    """The naif-499 `seasonal` payload: piecewise-linear factors on the L_s grid.

    τ scales the dust column, Conrath-derived scale height replaces
    mie_scale_height_km, pressure scales the Rayleigh column (normalised to the
    annual mean so the shipped 636 Pa datum is the mean).
    """
    mars = ATMOSPHERE_BODIES["naif-499"]
    level = render_conditions("naif-499", mars)
    gas_h = scale_height_km(
        mean_molar_mass_g_mol(level.composition), level.temperature_k, mars.gravity_m_s2
    )
    aerosol_h = AEROSOLS[mars.aerosol].scale_height_km
    tau_min = min(MARS_DUST_TAU_VIS)
    tau_max = max(MARS_DUST_TAU_VIS)
    ln_clear = math.log(MARS_CONRATH_NU_CLEAR)
    ln_dusty = math.log(MARS_CONRATH_NU_DUSTY)
    mean_pressure = sum(MARS_PRESSURE_MBAR) / len(MARS_PRESSURE_MBAR)

    dust_h = []
    for tau in MARS_DUST_TAU_VIS:
        # Dustier air mixes dust deeper: interpolate ν in log space between the
        # clear/confined and storm/deep-mixed anchors on the season's dustiness.
        dustiness = (tau - tau_min) / (tau_max - tau_min)
        nu = math.exp(ln_clear + (ln_dusty - ln_clear) * dustiness)
        # Scale relative to the shipped well-mixed column so the clear-season
        # baseline stays exactly the tuned look.
        h_eff = conrath_dust_scale_height_km(nu, gas_h)
        h_well_mixed = conrath_dust_scale_height_km(MARS_CONRATH_NU_DUSTY, gas_h)
        dust_h.append(round(aerosol_h * h_eff / h_well_mixed, 2))

    return {
        "ls_deg": list(MARS_SEASON_LS_DEG),
        "dust_tau_factor": [
            round(tau / MARS_DUST_TAU_CLEAR, 3) for tau in MARS_DUST_TAU_VIS
        ],
        "dust_scale_height_km": dust_h,
        "pressure_factor": [round(p / mean_pressure, 3) for p in MARS_PRESSURE_MBAR],
    }
