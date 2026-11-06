"""Interior models of stars other than the Sun, read from papers.

An entry is keyed like `constants/stars/literature.py`: an id of the star that
stays the same between ingests (here the HIP number), never our own ID. The
extrasolar export finds the star's ID in the registry and ships the entry in
the star's `interior` row as tier 0, in the shape that `naif-10` takes.

Each number is read in the cited paper. A radius in km is the paper's r/R
times its R, so those layers are `derived`. A layer carries a composition
only where the paper gives that layer's own abundances: the surface for a
convective envelope. The abundances at the centre are in
`centre_composition`, also for a mixed convective core, so that the panel
shows them in one place for every star. A layer whose top the paper does
not give has no `outer_radius_km`.

A layer has a mass fraction where the paper gives one. A paper gives the
mass of the core and of no other layer, so the block has no composition bar.

The outermost layer has the paper's Teff as its `outer_temperature_k`. No
other table holds the surface temperature of these stars.
"""

from space_map_data.constants.interior.schema import (
    HEAVY_ELEMENTS,
    HELIUM,
    HYDROGEN,
    BodyInterior,
    Component,
    Layer,
)
from space_map_data.constants.planets.families import SOLAR_RADIUS_KM
from space_map_data.constants.stars.literature import StarKey

# The month the standings below were last read against the literature.
READ_AS_OF = "2026-11"


def _hip(number: int) -> StarKey:
    return ("hip", "2007", str(number))


def _mix(source: str, x: float, y: float) -> tuple[Component, ...]:
    """H, He and the rest by difference, as the paper gives X and Y."""
    return (
        Component(HYDROGEN, x, source),
        Component(HELIUM, y, source),
        Component(HEAVY_ELEMENTS, round(1.0 - x - y, 4), source),
    )


def _one(
    material: str,
    fraction: float,
    source: str,
    fraction_range: tuple[float, float] | None = None,
) -> tuple[Component]:
    """The one centre fraction that the paper gives."""
    return (Component(material, fraction, source, fraction_range),)


# α Cen A and B: one calibration of the pair on the large and small spacings
# of A (Thévenin et al. 2002, Table 1). B has no modes of its own in the fit,
# so its layers are the model's, not seismic. Tcz is in MK, as Tc is. The
# table gives no Teff of the models, so the Teff is the observed one that the
# calibration fits.
_THEVENIN = "thevenin_2002"
_A_RADIUS = 1.230 * SOLAR_RADIUS_KM
_B_RADIUS = 0.857 * SOLAR_RADIUS_KM

# Procyon A: the raOvD model at β = 1.0, the subgrid of highest evidence
# (Guenther et al. 2014, Table 4). The table gives Zs/Xs but not Xs and Ys,
# so the envelope has no composition. Mcc/M is 0.123 ± 0.008. The table's
# ±0.04 dex on log Teff is wider than the Teff box of the grid (Sect. 2), so
# the Teff has no range.
_GUENTHER = "guenther_2014"
_PROCYON_RADIUS = 10**0.312 * SOLAR_RADIUS_KM
_PROCYON_TEFF = 10**3.820

# Sirius A: model d, the adopted one (Kervella et al. 2003, Table 3 and
# Sect. 5). Xs = (1 − Ys) / (1 + (Z/X)s) from Ys = 0.200 and (Z/X)s = 0.0099.
# The paper names a convective core but gives no size, so it has no layer.
# The Teff is that of model d, without a range.
_KERVELLA = "kervella_2003"
_SIRIUS_RADIUS = 1.7105 * SOLAR_RADIUS_KM
_SIRIUS_XS = round((1.0 - 0.200) / (1.0 + 0.0099), 4)

# μ Ara: Table 7 for R and Teff; the core of the αov = 0.005 model of Table 6,
# the upper limit that the paper sets on overshoot (Soriano & Vauclair 2010).
# The paper gives no base of the convective envelope, and the central YC
# without its X.
_SORIANO = "soriano_2010"
_MU_ARA_RADIUS = 1.36 * SOLAR_RADIUS_KM

# ν Eri: the αov = 0 model of Table 1 (Pamyatnykh et al. 2004), which the
# paper's bound αov < 0.12 favours. X = 0.7 and Z = 0.015 are the models'
# initial values. The table gives the core's Xc and Mmix/M, the mass of the
# mixed core.
_PAMYATNYKH = "pamyatnykh_2004"
_NU_ERI_RADIUS = 6.279 * SOLAR_RADIUS_KM
_NU_ERI_TEFF = 10**4.3553

# β CMa: the 13.5 M☉ model of Table 3 (Mazumdar et al. 2006), the paper's
# adopted mass. No model fits without core overshoot, so the core is there,
# but the table gives no size. The range of Xc is that of the five models of
# the table.
_MAZUMDAR = "mazumdar_2006"
_BETA_CMA_TEFF = 10**4.373

STAR_INTERIORS: dict[StarKey, BodyInterior] = {
    # α Cen A, HD 128620.
    _hip(71683): BodyInterior(
        structure="fluid",
        structure_source=_THEVENIN,
        layers=(
            Layer(
                role="convective_zone",
                mass_fraction=None,
                composition=_mix(_THEVENIN, 0.715, 0.258),
                source=_THEVENIN,
                outer_radius_km=_A_RADIUS,
                derived=True,
                state="plasma",
                evidence="seismic",
                outer_temperature_k=5790.0,
                outer_temperature_range_k=(5760.0, 5820.0),
                temperature_sources=(_THEVENIN,),
            ),
            Layer(
                role="radiative_zone",
                mass_fraction=None,
                composition=(),
                source=_THEVENIN,
                outer_radius_km=0.725 * _A_RADIUS,
                derived=True,
                state="plasma",
                evidence="seismic",
                outer_temperature_k=1.893e6,
                temperature_sources=(_THEVENIN,),
            ),
            # Models with and without this core fit the same modes.
            Layer(
                role="convective_core",
                mass_fraction=None,
                composition=(),
                source=_THEVENIN,
                outer_radius_km=0.052 * _A_RADIUS,
                derived=True,
                state="plasma",
                evidence="seismic",
                standing="disputed",
                standing_as_of=READ_AS_OF,
                standing_sources=("demeulenaer_2010", "nsamba_2018"),
            ),
        ),
        centre_temperature_k=19.00e6,
        centre_temperature_sources=(_THEVENIN,),
        centre_density_g_cm3=177.1,
        centre_density_sources=(_THEVENIN,),
        centre_composition=_mix(_THEVENIN, 0.182, 0.785),
    ),
    # α Cen B, HD 128621.
    _hip(71681): BodyInterior(
        structure="fluid",
        structure_source=_THEVENIN,
        layers=(
            Layer(
                role="convective_zone",
                mass_fraction=None,
                composition=_mix(_THEVENIN, 0.694, 0.277),
                source=_THEVENIN,
                outer_radius_km=_B_RADIUS,
                derived=True,
                state="plasma",
                evidence="thermal_model",
                outer_temperature_k=5260.0,
                outer_temperature_range_k=(5210.0, 5310.0),
                temperature_sources=(_THEVENIN,),
            ),
            Layer(
                role="radiative_zone",
                mass_fraction=None,
                composition=(),
                source=_THEVENIN,
                outer_radius_km=0.679 * _B_RADIUS,
                derived=True,
                state="plasma",
                evidence="thermal_model",
                outer_temperature_k=2.802e6,
                temperature_sources=(_THEVENIN,),
            ),
        ),
        centre_temperature_k=13.89e6,
        centre_temperature_sources=(_THEVENIN,),
        centre_density_g_cm3=117.1,
        centre_density_sources=(_THEVENIN,),
        centre_composition=_mix(_THEVENIN, 0.428, 0.539),
    ),
    # Procyon A, HD 61421.
    _hip(37279): BodyInterior(
        structure="fluid",
        structure_source=_GUENTHER,
        layers=(
            Layer(
                role="convective_zone",
                mass_fraction=None,
                composition=(),
                source=_GUENTHER,
                outer_radius_km=_PROCYON_RADIUS,
                derived=True,
                state="plasma",
                evidence="seismic",
                outer_temperature_k=_PROCYON_TEFF,
                temperature_sources=(_GUENTHER,),
            ),
            Layer(
                role="radiative_zone",
                mass_fraction=None,
                composition=(),
                source=_GUENTHER,
                outer_radius_km=0.917 * _PROCYON_RADIUS,
                derived=True,
                state="plasma",
                evidence="seismic",
            ),
            Layer(
                role="convective_core",
                mass_fraction=0.123,
                mass_fraction_range=(0.115, 0.131),
                composition=(),
                source=_GUENTHER,
                outer_radius_km=0.073 * _PROCYON_RADIUS,
                derived=True,
                state="plasma",
                evidence="seismic",
            ),
        ),
    ),
    # Sirius A, HD 48915.
    _hip(32349): BodyInterior(
        structure="fluid",
        structure_source=_KERVELLA,
        layers=(
            Layer(
                role="convective_zone",
                mass_fraction=None,
                composition=_mix(_KERVELLA, _SIRIUS_XS, 0.200),
                source=_KERVELLA,
                outer_radius_km=_SIRIUS_RADIUS,
                derived=True,
                state="plasma",
                evidence="thermal_model",
                outer_temperature_k=9936.0,
                temperature_sources=(_KERVELLA,),
            ),
            Layer(
                role="radiative_zone",
                mass_fraction=None,
                composition=(),
                source=_KERVELLA,
                outer_radius_km=0.9926 * _SIRIUS_RADIUS,
                derived=True,
                state="plasma",
                evidence="thermal_model",
            ),
        ),
        centre_temperature_k=22.46e6,
        centre_temperature_sources=(_KERVELLA,),
        centre_composition=_one(HYDROGEN, 0.590, _KERVELLA),
    ),
    # μ Ara, HD 160691.
    _hip(86796): BodyInterior(
        structure="fluid",
        structure_source=_SORIANO,
        layers=(
            Layer(
                role="convective_zone",
                mass_fraction=None,
                composition=(),
                source=_SORIANO,
                outer_radius_km=_MU_ARA_RADIUS,
                derived=True,
                state="plasma",
                evidence="seismic",
                outer_temperature_k=5820.0,
                outer_temperature_range_k=(5770.0, 5870.0),
                temperature_sources=(_SORIANO,),
            ),
            Layer(
                role="radiative_zone",
                mass_fraction=None,
                composition=(),
                source=_SORIANO,
                state="plasma",
                evidence="seismic",
            ),
            Layer(
                role="convective_core",
                mass_fraction=None,
                composition=(),
                source=_SORIANO,
                outer_radius_km=0.050 * _MU_ARA_RADIUS,
                derived=True,
                state="plasma",
                evidence="seismic",
            ),
        ),
        centre_composition=_one(HELIUM, 0.9482, _SORIANO),
    ),
    # ν Eri, HD 29248.
    _hip(21444): BodyInterior(
        structure="fluid",
        structure_source=_PAMYATNYKH,
        layers=(
            Layer(
                role="radiative_zone",
                mass_fraction=None,
                composition=_mix(_PAMYATNYKH, 0.7, 0.285),
                source=_PAMYATNYKH,
                outer_radius_km=_NU_ERI_RADIUS,
                derived=True,
                state="plasma",
                evidence="seismic",
                outer_temperature_k=_NU_ERI_TEFF,
                temperature_sources=(_PAMYATNYKH,),
            ),
            Layer(
                role="convective_core",
                mass_fraction=0.189,
                composition=(),
                source=_PAMYATNYKH,
                outer_radius_km=0.117 * _NU_ERI_RADIUS,
                derived=True,
                state="plasma",
                evidence="seismic",
            ),
        ),
        centre_composition=_one(HYDROGEN, 0.2414, _PAMYATNYKH),
    ),
    # β CMa, HD 44743.
    _hip(30324): BodyInterior(
        structure="fluid",
        structure_source=_MAZUMDAR,
        layers=(
            # X0 and Z0 of the model; Y0 by difference.
            Layer(
                role="radiative_zone",
                mass_fraction=None,
                composition=_mix(_MAZUMDAR, 0.697, 0.282),
                source=_MAZUMDAR,
                outer_radius_km=10.50 * SOLAR_RADIUS_KM,
                derived=True,
                state="plasma",
                evidence="seismic",
                outer_temperature_k=_BETA_CMA_TEFF,
                temperature_sources=(_MAZUMDAR,),
            ),
            Layer(
                role="convective_core",
                mass_fraction=None,
                composition=(),
                source=_MAZUMDAR,
                state="plasma",
                evidence="seismic",
            ),
        ),
        centre_composition=_one(HYDROGEN, 0.128, _MAZUMDAR, (0.105, 0.134)),
    ),
}
