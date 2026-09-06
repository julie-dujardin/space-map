"""The optically thick column a shell's single-scatter march cannot light.

Venus's shell renders from the ~65 km cloud top, so a camera on the surface
sits under a column the shell never models: 92 bar of CO₂ (vertical Rayleigh
τ ≈ 7/17/41 at 680/550/440 nm), a τ ≈ 25 sulphuric-acid deck, a small-
particle haze under it and a gaseous absorber in the lowest 35 km. Light
only gets down by diffusing through all of it, which is what makes the Venera
sky orange: the upper cloud's near-UV absorber, Rayleigh back-scatter and the
sub-cloud absorber strip the blue, and the ground gets ~90 W m⁻² at the
subsolar point — 17 W m⁻², 2.5% of the incident sunlight, absorbed there on
average (Moroz et al. 1983, Icarus 53, 509; Tomasko et al. 1980, JGR 85,
8167). Titan's shell renders from its surface, but the τ ≈ 4 tholin haze
over it is just as far beyond single scattering: Huygens landed under a dim
orange overcast with the Sun a smudge (Tomasko et al. 2005, Nature 438,
765). export/atmospheres/deep_column.py solves the diffuse flux through
each column; the shell above (Venus) or over it (Titan) stays the march.
"""

from typing import NamedTuple

from space_map_data.constants.atmosphere.aerosols import AEROSOLS
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

# Titan, HASI descent (Fulchignoni et al. 2005, Nature 438, 785): 1.467 bar
# and 93.65 K at the surface, the 70.4 K tropopause at 44 km, then the
# stratospheric rise toward the 186 K stratopause near 250 km. Pressures
# are hydrostatic on those temperatures (N₂ + 5.65% CH₄ below the
# tropopause, 1.48% above; g = 1.35), within 10% of HASI's 0.115 bar at the
# tropopause.
TITAN_HASI_LEVELS: tuple[ProfileLevel, ...] = (
    ProfileLevel(0.0, 93.65, 1.467),
    ProfileLevel(10.0, 85.0, 0.878),
    ProfileLevel(20.0, 78.0, 0.482),
    ProfileLevel(30.0, 74.0, 0.245),
    ProfileLevel(44.0, 70.4, 0.0967),
    ProfileLevel(60.0, 82.0, 0.0354),
    ProfileLevel(80.0, 105.0, 0.0126),
    ProfileLevel(100.0, 128.0, 0.00559),
    ProfileLevel(120.0, 145.0, 0.00281),
    ProfileLevel(150.0, 165.0, 0.00115),
    ProfileLevel(200.0, 178.0, 0.000241),
    ProfileLevel(250.0, 186.0, 0.0000546),
)


class HazeSlab(NamedTuple):
    """Aerosol over [base, top]: extinction optical depth and single-
    scattering albedo per channel; `asymmetry` None takes the shell
    aerosol's per-channel value. `shape` "uniform" spreads `tau` evenly over
    the slab; "profile" follows the body's shipped Mie-density profile, and
    `tau` is then the whole column's — the slab keeps the profile's share
    between base and top, so one column can change albedo with altitude."""

    tau: tuple[float, float, float]
    albedo: tuple[float, float, float]
    base_km: float
    top_km: float
    asymmetry: float | None = None
    shape: str = "uniform"


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
    # Height of the column over the solid surface, km. A deck body's shell
    # renders from here (Venus); a surface-referenced shell marches over it
    # (Titan).
    top_km: float
    hazes: tuple[HazeSlab, ...]
    # Solid-surface albedo per channel — the ground bounce under the column.
    ground_albedo: tuple[float, float, float]
    cloud_layers: tuple[VenusCloudLayer, ...] = ()
    # Single-scattering albedo per channel at 680/550/440 nm, by layer name.
    cloud_albedo: dict[str, tuple[float, float, float]] = {}
    absorber: AbsorberTent | None = None


_TITAN_THOLIN = AEROSOLS["titan_tholin"]
# The shell aerosol's whole column, per channel.
_TITAN_TAU: tuple[float, float, float] = tuple(
    (s + a) * _TITAN_THOLIN.scale_height_km
    for s, a in zip(_TITAN_THOLIN.scatter_per_km, _TITAN_THOLIN.absorption_per_km)
)

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
        top_km=65.0,
        hazes=(
            HazeSlab(
                tau=(0.84, 1.59, 3.1),
                albedo=(1.0, 1.0, 1.0),
                base_km=30.0,
                top_km=48.0,
                asymmetry=0.4,
            ),
        ),
        ground_albedo=(0.10, 0.09, 0.08),
        cloud_layers=VENUS_CLOUD_LAYERS,
        cloud_albedo={
            "upper haze": (0.9998, 0.9995, 0.988),
            "upper cloud": (0.9998, 0.9995, 0.988),
            "middle cloud": (0.9995, 0.9995, 0.9995),
            "lower cloud": (0.9995, 0.9995, 0.9995),
        },
        absorber=AbsorberTent(
            albedo_deficit=(0.0, 0.0015, 0.006),
            base_km=0.0,
            peak_km=15.0,
            top_km=35.0,
        ),
    ),
    # The haze below 120 km — 70% of the column, τ ≈ 2 at 550 nm left
    # above it for the shell to march. Extinction is the shell aerosol's
    # column on the shipped Doose et al. 2016 profile, in the three altitude
    # regimes of Tomasko et al. 2008 table 2 with their measured single-
    # scattering albedos at 675/555/430 nm: 0.97/0.955/0.92 below 30 km,
    # 0.99/0.968/0.925 at 80 km, 0.93/0.91/0.82 at 144 km (the mean of the
    # last two above 80 km). The dark laboratory tholin belongs to the high
    # haze that colours the disc, not to the condensate-grown particles
    # under it — the two-stream stack does the multiple scattering itself.
    # Ground: DISR surface reflectance ≈ 0.15 in the red, falling into the
    # blue (Tomasko et al. 2005).
    "naif-606": DeepColumn(
        profile=TITAN_HASI_LEVELS,
        top_km=120.0,
        hazes=(
            HazeSlab(_TITAN_TAU, (0.97, 0.955, 0.92), 0.0, 30.0, shape="profile"),
            HazeSlab(_TITAN_TAU, (0.99, 0.968, 0.925), 30.0, 80.0, shape="profile"),
            HazeSlab(_TITAN_TAU, (0.96, 0.94, 0.87), 80.0, 600.0, shape="profile"),
        ),
        ground_albedo=(0.16, 0.13, 0.10),
    ),
}
