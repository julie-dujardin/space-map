"""Diffuse sunlight through the column under a shell's render level.

A single-scatter march cannot light a column this thick (Venus: τ ≈ 60 at
440 nm) — sunlight arrives at the ground by diffusion. Each channel is solved
as a stack of thin homogeneous sublayers (Rayleigh gas + cloud deck +
sub-cloud haze + gaseous absorber) with the delta-Eddington two-stream
reflectance/transmittance of each, combined by the adding method for diffuse
incidence from the top and a Lambertian ground. Shipped as a `DEEP_N`-level profile over [0, reference
altitude]: downward flux (over the surface value's luminance, so the ground
light keeps its colour at unit brightness), upward/downward flux ratio, and
the direct-beam extinction — the frontend's deep-column sky samples it at the
camera's altitude and fogs terrain with the extinction.
"""

import logging
import math

from space_map_data.constants.atmosphere.bodies import (
    RENDER_WAVELENGTHS_M,
    BodyAtmosphere,
)
from space_map_data.constants.atmosphere.deep_column import (
    DEEP_COLUMNS,
    DeepColumn,
    ProfileLevel,
)
from space_map_data.export.atmospheres.conditions import render_conditions
from space_map_data.export.atmospheres.rayleigh import rayleigh_beta_per_m

logger = logging.getLogger(__name__)

DEEP_N = 64
# Sublayer thickness for the two-stream stack; the sharp lower cloud base
# (3 km thick) needs finer steps than the shipped profile.
_SUBLAYER_KM = 0.25
# Photopic luminance weights (Rec. 709) at the render wavelengths.
_LUMINANCE = (0.2126, 0.7152, 0.0722)


def eddington_layer(tau: float, omega: float, g: float) -> tuple[float, float]:
    """Diffuse (reflectance, transmittance) of one homogeneous layer, delta-
    Eddington two-stream (Joseph et al. 1976; Meador & Weaver 1980 eq. 21-22
    with the Eddington γ₁, γ₂). The conservative limit is R = γ₁τ/(1 + γ₁τ)."""
    f = g * g
    tau = (1.0 - omega * f) * tau
    omega = (1.0 - f) * omega / (1.0 - omega * f)
    g = (g - f) / (1.0 - f)
    g1 = (7.0 - omega * (4.0 + 3.0 * g)) / 4.0
    g2 = -(1.0 - omega * (4.0 - 3.0 * g)) / 4.0
    k2 = g1 * g1 - g2 * g2
    if k2 < 1e-12:
        r = g1 * tau / (1.0 + g1 * tau)
        return r, 1.0 - r
    k = math.sqrt(k2)
    e = math.exp(-2.0 * k * tau)
    denom = k + g1 + (k - g1) * e
    return g2 * (1.0 - e) / denom, 2.0 * k * math.exp(-k * tau) / denom


def _interpolate_level(
    profile: tuple[ProfileLevel, ...], z_km: float
) -> tuple[float, float]:
    """(T, P[Pa]) at `z_km`: temperature linear, pressure log-linear."""
    lo = profile[0]
    for hi in profile[1:]:
        if z_km <= hi.altitude_km:
            w = (z_km - lo.altitude_km) / (hi.altitude_km - lo.altitude_km)
            t = lo.temperature_k + w * (hi.temperature_k - lo.temperature_k)
            p = math.exp(
                math.log(lo.pressure_bar)
                + w * (math.log(hi.pressure_bar) - math.log(lo.pressure_bar))
            )
            return t, p * 1e5
        lo = hi
    return lo.temperature_k, lo.pressure_bar * 1e5


def _tent(z_km: float, base: float, peak: float, top: float) -> float:
    if z_km <= base or z_km >= top:
        return 0.0
    if z_km <= peak:
        return (z_km - base) / (peak - base)
    return (top - z_km) / (top - peak)


def _solve_channel(
    column: DeepColumn,
    composition: dict[str, float],
    top_km: float,
    wavelength_m: float,
    channel: int,
    cloud_g: float,
) -> tuple[list[float], list[float], list[float], float]:
    """Returns (F_down, F_up) at each sublayer interface from the ground up,
    the sublayer extinction per km, and the column's diffuse reflectance —
    for unit diffuse flux entering at `top_km`."""
    n = int(round(top_km / _SUBLAYER_KM))
    dz = top_km / n
    absorber = column.absorber
    haze = column.subcloud_haze
    layers: list[tuple[float, float, float]] = []
    extinction: list[float] = []
    for i in range(n):
        z = (i + 0.5) * dz
        t_k, p_pa = _interpolate_level(column.profile, z)
        tau_r = rayleigh_beta_per_m(composition, p_pa, t_k, wavelength_m) * 1e3 * dz
        # Cloud scattering and absorption, layer by layer.
        cloud_scatter = 0.0
        cloud_absorb = 0.0
        for layer in column.cloud_layers:
            top = min(layer.top_km, top_km)
            if layer.base_km <= z < top:
                tau_mid = 0.5 * (layer.tau_min + layer.tau_max)
                tau_layer = tau_mid * dz / (top - layer.base_km)
                omega = column.cloud_albedo[layer.name][channel]
                cloud_scatter += omega * tau_layer
                cloud_absorb += (1.0 - omega) * tau_layer
        tau_h = 0.0
        if haze.base_km <= z < min(haze.top_km, top_km):
            tau_h = haze.tau[channel] * dz / (min(haze.top_km, top_km) - haze.base_km)
        # The absorber rides the gas: its deficit scales the local Rayleigh depth.
        tau_a = (
            absorber.albedo_deficit[channel]
            * _tent(z, absorber.base_km, absorber.peak_km, absorber.top_km)
            * tau_r
        )
        scattered = tau_r + cloud_scatter + tau_h
        tau = scattered + cloud_absorb + tau_a
        g = (cloud_scatter * cloud_g + tau_h * haze.asymmetry) / scattered
        layers.append((tau, scattered / tau, g))
        extinction.append(tau / dz)
    rt = [eddington_layer(*layer) for layer in layers]
    # Reflectance of everything under interface i (interface i = the bottom of
    # sublayer i; interface 0 is the ground).
    r_below = [column.ground_albedo[channel]]
    for r, t in rt:
        prev = r_below[-1]
        r_below.append(r + t * t * prev / (1.0 - r * prev))
    f_down = [0.0] * (n + 1)
    f_down[n] = 1.0
    for i in range(n - 1, -1, -1):
        r, t = rt[i]
        f_down[i] = f_down[i + 1] * t / (1.0 - r * r_below[i])
    f_up = [r_below[i] * f_down[i] for i in range(n + 1)]
    return f_down, f_up, extinction, r_below[n]


def _resample(values: list[float], dz: float, z_km: float) -> float:
    """Linear interpolation of an interface-indexed list at `z_km`."""
    w = min(max(z_km / dz, 0.0), len(values) - 1.0)
    i0 = min(int(w), len(values) - 2)
    return values[i0] + (values[i0 + 1] - values[i0]) * (w - i0)


def build_deep_column(
    object_id: str, body: BodyAtmosphere, cloud_g: dict[str, float]
) -> dict | None:
    """The `deep_column` payload block, or None for bodies rendered from
    their surface. `cloud_g` is the deck aerosol's per-channel asymmetry."""
    column = DEEP_COLUMNS.get(object_id)
    if column is None:
        return None
    if body.reference_altitude_km <= 0:
        raise ValueError(f"{object_id}: deep column needs a reference altitude")
    top_km = body.reference_altitude_km
    composition = render_conditions(object_id, body).composition
    n_sub = int(round(top_km / _SUBLAYER_KM))
    dz = top_km / n_sub
    channels = [
        _solve_channel(column, composition, top_km, wavelength, c, cloud_g[name])
        for c, (name, wavelength) in enumerate(RENDER_WAVELENGTHS_M.items())
    ]
    surface_fraction = [f_down[0] for f_down, _, _, _ in channels]
    top_reflectance = [reflectance for _, _, _, reflectance in channels]
    surface_luminance = sum(w * f for w, f in zip(_LUMINANCE, surface_fraction))
    flux_down: list[float] = []
    flux_up_ratio: list[float] = []
    extinction_per_km: list[float] = []
    for f_down, f_up, ext, _ in channels:
        # Extinction is per sublayer; index it by the sublayer holding z.
        ext_at = [ext[min(int(k), n_sub - 1)] for k in range(n_sub + 1)]
        for i in range(DEEP_N):
            z = top_km * i / (DEEP_N - 1)
            down = _resample(f_down, dz, z)
            up = _resample(f_up, dz, z)
            flux_down.append(down / surface_luminance)
            flux_up_ratio.append(up / down)
            extinction_per_km.append(_resample(ext_at, dz, z))
    logger.info(
        "%s deep column: surface flux (%.3f, %.3f, %.3f) of incident, "
        "top reflectance (%.2f, %.2f, %.2f)",
        object_id,
        *surface_fraction,
        *top_reflectance,
    )
    return {
        # Channel-major: DEEP_N values for R, then G, then B.
        "flux_down": [_sig(v) for v in flux_down],
        "flux_up_ratio": [_sig(v) for v in flux_up_ratio],
        "extinction_per_km": [_sig(v) for v in extinction_per_km],
        "surface_flux_fraction": [_sig(v) for v in surface_fraction],
        "top_reflectance": [_sig(v) for v in top_reflectance],
    }


def _sig(value: float, digits: int = 4) -> float:
    if value == 0:
        return 0.0
    return float(f"{value:.{digits}g}")
