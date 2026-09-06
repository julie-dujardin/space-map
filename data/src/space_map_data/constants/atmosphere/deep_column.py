"""The atmosphere under a shell's render level.

Venus's shell renders from the ~65 km cloud top, so a camera on the surface
sits under a column the shell never models: 92 bar of CO₂ (vertical Rayleigh
τ ≈ 7/17/41 at 680/550/440 nm), a τ ≈ 25 sulphuric-acid deck, a small-
particle haze under it and a gaseous absorber in the lowest 35 km. Light
only gets down by diffusing through all of it, which is what makes the Venera
sky orange: the upper cloud's near-UV absorber, Rayleigh back-scatter and the
sub-cloud absorber strip the blue, and the ground gets ~90 W m⁻² at the
subsolar point — 17 W m⁻², 2.5% of the incident sunlight, absorbed there on
average (Moroz et al. 1983, Icarus 53, 509; Tomasko et al. 1980, JGR 85,
8167). export/atmospheres/deep_column.py solves the diffuse flux through it.
"""

from typing import NamedTuple

from space_map_data.constants.atmosphere.layers import (
    VENUS_CLOUD_LAYERS,
    VenusCloudLayer,
)


class ProfileLevel(NamedTuple):
    altitude_km: float
    temperature_k: float
    pressure_bar: float


# VIRA deep-atmosphere model, Seiff et al. 1985 (Adv. Space Res. 5(11), 3),
# Table 1-1: altitudes above the 6052 km radius; 2 km rows above 60 km.
VENUS_VIRA_LEVELS: tuple[ProfileLevel, ...] = (
    ProfileLevel(0.0, 735.3, 92.10),
    ProfileLevel(5.0, 696.8, 66.65),
    ProfileLevel(10.0, 658.2, 47.39),
    ProfileLevel(15.0, 620.8, 33.04),
    ProfileLevel(20.0, 580.7, 22.52),
    ProfileLevel(25.0, 539.2, 14.93),
    ProfileLevel(30.0, 496.9, 9.581),
    ProfileLevel(35.0, 455.5, 5.917),
    ProfileLevel(40.0, 417.6, 3.501),
    ProfileLevel(45.0, 385.4, 1.979),
    ProfileLevel(50.0, 350.5, 1.066),
    ProfileLevel(55.0, 302.3, 0.5314),
    ProfileLevel(60.0, 262.8, 0.2357),
    ProfileLevel(62.0, 254.5, 0.1659),
    ProfileLevel(64.0, 245.4, 0.1156),
    ProfileLevel(66.0, 241.0, 0.0797),
    ProfileLevel(68.0, 235.4, 0.0545),
    ProfileLevel(70.0, 229.8, 0.0369),
)


class SubcloudHaze(NamedTuple):
    """Conservative small-particle haze under the cloud base: column optical
    depth per channel, spread uniformly over [base, top]."""

    tau: tuple[float, float, float]
    base_km: float
    top_km: float
    asymmetry: float


class AbsorberTent(NamedTuple):
    """Gaseous absorber mixed into the air: the gas's single-scattering albedo
    deficit (1 − ω) per channel at the tent's peak, with a linear-tent
    mixing-ratio profile over [base, top] peaking at `peak`."""

    albedo_deficit: tuple[float, float, float]
    base_km: float
    peak_km: float
    top_km: float


class DeepColumn(NamedTuple):
    profile: tuple[ProfileLevel, ...]
    cloud_layers: tuple[VenusCloudLayer, ...]
    # Single-scattering albedo per channel at 680/550/440 nm, by layer name.
    cloud_albedo: dict[str, tuple[float, float, float]]
    subcloud_haze: SubcloudHaze
    absorber: AbsorberTent
    # Solid-surface albedo per channel — the ground bounce under the column.
    ground_albedo: tuple[float, float, float]


DEEP_COLUMNS: dict[str, DeepColumn] = {
    # Deck: the LCPS layers of layers.py at their mid-range τ (0.63 µm; the
    # droplets are 1-4 µm, so grey across the visible; Venera 11/12 got
    # 29-38 below 63 km, Pioneer Venus ~25). Albedo: conservative below
    # 58 km — (1 − ω) < 10⁻³ at 0.49 and 0.7 µm — rising above 60 km
    # (Moroz et al. 1983), where the unknown near-UV absorber lives; its
    # blue-channel value is the tunable, set so the column's top reflectance
    # dips ~20% from green to blue like the spherical albedo. Sub-cloud haze:
    # τ 1.5-3 at 0.49 µm, 0.13-0.4 at 1 µm (λ⁻³, ~0.1 µm particles) below
    # 48 km; absorber: true absorption at λ < 0.55 µm below 35 km, peaking
    # near 15 km with (1 − ω) = 5×10⁻³ at 0.49 µm, most likely S₃/S₄
    # (both Moroz et al. 1983). Ground: ~0.1 through the visible, rising
    # into the red (Ekonomov et al. 1980 fig. 8, Venera 9/10); dark and
    # colourless once the orange illumination is removed (Pieters et al.
    # 1986, which also saw no blue signal at all at the surface).
    "naif-299": DeepColumn(
        profile=VENUS_VIRA_LEVELS,
        cloud_layers=VENUS_CLOUD_LAYERS,
        cloud_albedo={
            "upper haze": (0.9998, 0.9995, 0.988),
            "upper cloud": (0.9998, 0.9995, 0.988),
            "middle cloud": (0.9995, 0.9995, 0.9995),
            "lower cloud": (0.9995, 0.9995, 0.9995),
        },
        subcloud_haze=SubcloudHaze(
            tau=(0.84, 1.59, 3.1), base_km=30.0, top_km=48.0, asymmetry=0.4
        ),
        absorber=AbsorberTent(
            albedo_deficit=(0.0, 0.0015, 0.006),
            base_km=0.0,
            peak_km=15.0,
            top_km=35.0,
        ),
        ground_albedo=(0.10, 0.09, 0.08),
    ),
}
