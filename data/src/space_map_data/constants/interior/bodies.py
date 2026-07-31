"""Per-body interior models, one entry per body a mission or a seismometer
has actually constrained.

Every mass fraction is either quoted from the cited work or marked `derived`
and computed here from that work's radii and densities — the arithmetic is
written out in the comment so it can be checked. Nothing is carried over from
a compilation without reading the source, and a body whose split cannot be
sourced is absent rather than estimated.

Layers run outermost to innermost. Fractions within a body are of its total
mass and are expected to sum to ~1; the export checks that.
"""

from space_map_data.constants.interior.schema import (
    BodyInterior,
    Component,
    Detail,
    ELEMENT_WEIGHT,
    Layer,
    METAL,
    OXIDE_WEIGHT,
    SILICATE,
    WATER,
)


INTERIOR_FACTS: dict[str, BodyInterior] = {
    # Mercury, the one terrestrial planet that is mostly core. MESSENGER's
    # moment-of-inertia pair puts the top of the liquid core at 2020 ± 30 km
    # under a solid shell 410 ± 37 km thick of density 3650 ± 225 kg/m³:
    #   (4/3)π(2439.7³ - 2020³) km³ = 2.630e19 m³ × 3650 = 9.60e22 kg
    #   9.60e22 / 3.3011e23 = 0.291 shell, so 0.709 core
    "naif-199": BodyInterior(
        structure="differentiated",
        structure_source="hauck_2013",
        layers=(
            Layer(
                role="mantle",
                mass_fraction=0.291,
                composition=(Component(SILICATE, 1.0, "hauck_2013"),),
                source="hauck_2013",
                outer_radius_km=2439.7,
                derived=True,
                note="from_moment_of_inertia",
            ),
            # Fe-S-Si, with a solid FeS layer possibly floating at its top and
            # a solid inner core below — none of which is resolved well enough
            # to split into separate layers, so it stays one metal core.
            Layer(
                role="core",
                mass_fraction=0.709,
                composition=(Component(METAL, 1.0, "hauck_2013"),),
                source="hauck_2013",
                outer_radius_km=2020.0,
                derived=True,
            ),
        ),
    ),
    # Earth. Layer masses are quoted directly: McDonough 2003 tabulates the
    # Earth at 5.9736e24 kg against an inner core of 9.675e22, an outer core
    # of 1.835e24 and a mantle of 4.043e24 — so the core is 32.3% of the
    # planet and the inner core 5.0% of the core.
    "naif-399": BodyInterior(
        structure="differentiated",
        structure_source="dziewonski_1981",
        layers=(
            Layer(
                role="mantle",
                mass_fraction=0.6768,
                composition=(Component(SILICATE, 1.0, "mcdonough_1995"),),
                source="mcdonough_2003",
                outer_radius_km=6371.0,
                # Bulk silicate Earth, the pyrolite model. Crust is folded in:
                # at 0.4% of the planet it is a rounding error on this bar,
                # and separating it would need a second source.
                detail=Detail(
                    unit=OXIDE_WEIGHT,
                    entries=(
                        ("SiO2", 0.450),
                        ("MgO", 0.378),
                        ("FeO", 0.081),
                        ("Al2O3", 0.045),
                        ("CaO", 0.036),
                    ),
                    source="mcdonough_1995",
                ),
            ),
            Layer(
                role="outer_core",
                mass_fraction=0.3071,
                composition=(Component(METAL, 1.0, "mcdonough_2003"),),
                source="mcdonough_2003",
                outer_radius_km=3480.0,
                # The light elements are alloyed into the metal rather than
                # sitting as a separate sulphide phase, so the layer stays one
                # material and the split lives here.
                detail=Detail(
                    unit=ELEMENT_WEIGHT,
                    entries=(
                        ("Fe", 0.855),
                        ("Si", 0.060),
                        ("Ni", 0.052),
                        ("S", 0.019),
                        ("Co", 0.0025),
                    ),
                    source="mcdonough_2003",
                ),
            ),
            Layer(
                role="inner_core",
                mass_fraction=0.0162,
                composition=(Component(METAL, 1.0, "mcdonough_2003"),),
                source="mcdonough_2003",
                outer_radius_km=1221.5,
            ),
        ),
    ),
    # Mars. InSight put the core-mantle boundary at 1830 ± 40 km with a mean
    # core density of 5.7-6.3 g/cm³. The mass fraction follows:
    #   (4/3)π(1830 km)³ = 2.567e19 m³ × 6000 kg/m³ = 1.54e23 kg
    #   1.54e23 / 6.4171e23 (Mars) = 0.240
    # The density range puts it between 0.228 and 0.252, hence `derived`.
    "naif-499": BodyInterior(
        structure="differentiated",
        structure_source="stahler_2021",
        layers=(
            # Crust: 24-72 km average thickness, bulk density at most 3100
            # kg/m³. Taking the midpoint of each,
            #   4π(3389.5 km)² × 48 km = 6.93e18 m³ × 2900 kg/m³ = 2.01e22 kg
            #   2.01e22 / 6.4171e23 = 0.031
            # The thickness range alone spans 0.016-0.047.
            Layer(
                role="crust",
                mass_fraction=0.031,
                composition=(Component(SILICATE, 1.0, "knapmeyer_endrun_2021"),),
                source="knapmeyer_endrun_2021",
                outer_radius_km=3389.5,
                derived=True,
            ),
            Layer(
                role="mantle",
                mass_fraction=0.729,
                composition=(Component(SILICATE, 1.0, "khan_2021"),),
                source="stahler_2021",
                outer_radius_km=3341.5,
                derived=True,
                # One rocky layer, not Earth's two: the core is large enough
                # that Mars never had room for a bridgmanite lower mantle.
                note="from_moment_of_inertia",
            ),
            Layer(
                role="core",
                mass_fraction=0.240,
                composition=(Component(METAL, 1.0, "stahler_2021"),),
                source="stahler_2021",
                outer_radius_km=1830.0,
                derived=True,
            ),
        ),
    ),
    # The Moon. Two independent measurements, one per end: GRAIL gives a crust
    # 34-43 km thick at a bulk density of 2550 kg/m³ (12% porous), and
    # VPREMOON's core-reflected shear phases give a core of 380 ± 40 km at
    # 5200 ± 1000 kg/m³.
    #   crust  4π(1737.4 km)² × 38.5 km = 1.460e18 m³ × 2550 = 3.72e21 kg → 0.051
    #   core   (4/3)π(380 km)³ = 2.299e17 m³ × 5200 = 1.20e21 kg      → 0.016
    #   mantle the remainder                                          → 0.933
    # The core's error bars are wide enough to span 0.009-0.026, which is the
    # honest width of "the Moon is 1.6% metal".
    "naif-301": BodyInterior(
        structure="differentiated",
        structure_source="garcia_2011",
        layers=(
            Layer(
                role="crust",
                mass_fraction=0.051,
                composition=(Component(SILICATE, 1.0, "wieczorek_2013"),),
                source="wieczorek_2013",
                outer_radius_km=1737.4,
                derived=True,
            ),
            Layer(
                role="mantle",
                mass_fraction=0.933,
                composition=(Component(SILICATE, 1.0, "garcia_2011"),),
                source="garcia_2011",
                outer_radius_km=1698.9,
                derived=True,
            ),
            Layer(
                role="core",
                mass_fraction=0.016,
                composition=(Component(METAL, 1.0, "garcia_2011"),),
                source="garcia_2011",
                outer_radius_km=380.0,
                derived=True,
            ),
        ),
    ),
    # Enceladus. Cassini's gravity solution gives a bulk density of 1609 kg/m³
    # against an ice mantle at 920 and an ocean at 1000, and models the body as
    # a core of radius xR and density Aρ₀ under an H₂O mantle of density ρ₀:
    #   ρ̄/ρ₀ = (A-1)x³ + 1, with ρ̄/ρ₀ = 1.73 for an ice mantle
    # A 2.5 g/cm³ core gives A = 2.69, so x³ = 0.73/1.69 = 0.433, x = 0.756 —
    # a core radius of 191 km, which is where the paper's own core estimate
    # lands. Masses follow from those radii and densities, then normalise:
    #   core   (4/3)π(191 km)³ × 2500 = 7.25e19 kg → 0.666
    #   shell  30 km of ice at 920               → 0.179
    #   ocean  the 31 km between them at 1000    → 0.155
    # A denser core (3.9 g/cm³) would put the rock at 0.55 instead, so treat
    # two-thirds rock as the middle of a real range, not a measurement.
    "naif-602": BodyInterior(
        structure="differentiated",
        structure_source="iess_2014",
        note="subsurface_ocean",
        layers=(
            Layer(
                role="ice_shell",
                mass_fraction=0.179,
                composition=(Component(WATER, 1.0, "iess_2014"),),
                source="iess_2014",
                outer_radius_km=252.1,
                derived=True,
            ),
            Layer(
                role="ocean",
                mass_fraction=0.155,
                composition=(Component(WATER, 1.0, "iess_2014"),),
                source="iess_2014",
                outer_radius_km=222.1,
                derived=True,
            ),
            Layer(
                role="core",
                mass_fraction=0.666,
                composition=(Component(SILICATE, 1.0, "iess_2014"),),
                source="iess_2014",
                outer_radius_km=191.0,
                derived=True,
                note="from_moment_of_inertia",
            ),
        ),
    ),
}
