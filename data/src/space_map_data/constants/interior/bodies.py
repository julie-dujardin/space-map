"""Per-body interior models, one entry per body a mission or a seismometer
has actually constrained.

Every mass fraction is either quoted from the cited work or marked `derived`
and computed here from that work's radii and densities — the arithmetic is
written out in the comment so it can be checked. Nothing is carried over from
a compilation without reading the source, and a body whose split cannot be
sourced is absent rather than estimated.

Layers run outermost to innermost. Fractions within a body are of its total
mass and are expected to sum to ~1; the export checks that. A body whose
source constrains geometry and composition but not masses — the Sun — carries
no mass fractions at all rather than some, and drops out of the roll-up.

Where a source publishes a width rather than a value, both ship: the point
value is what the roll-up uses and `mass_fraction_range` / `fraction_range`
is what the panel draws around it.
"""

from space_map_data.constants.interior.schema import (
    BodyInterior,
    Component,
    Detail,
    ELEMENT_WEIGHT,
    HEAVY_ELEMENTS,
    HELIUM,
    HYDROGEN,
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
    # MESSENGER's full-mission gravity later split the outer shell in two: a
    # crust averaging 35 km at 2800 kg/m³ over a mantle 400 kg/m³ denser.
    #   (4/3)π(2439.7³ - 2404.7³) km³ = 2.583e18 m³ × 2800 = 7.23e21 kg → 0.022
    # The same work puts the outer core at 1985 ± 39 km — consistent with the
    # 2020 ± 30 used above — and finds a solid inner core at 0.54 ± 0.20 of
    # that radius. Real, but the ratio's error bars cube into a factor of nine
    # in volume, so the core stays whole here rather than split on a number
    # that loose.
    "naif-199": BodyInterior(
        structure="differentiated",
        structure_source="hauck_2013",
        layers=(
            Layer(
                role="crust",
                mass_fraction=0.022,
                composition=(Component(SILICATE, 1.0, "genova_2019"),),
                source="genova_2019",
                outer_radius_km=2439.7,
                derived=True,
            ),
            Layer(
                role="mantle",
                mass_fraction=0.269,
                composition=(Component(SILICATE, 1.0, "hauck_2013"),),
                source="hauck_2013",
                outer_radius_km=2404.7,
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
    # The Moon, from three ends at once. GRAIL gives a crust 34-43 km thick at
    # a bulk density of 2550 kg/m³ (12% porous). Weber's array-stacked Apollo
    # seismograms resolve the core in two pieces — a fluid outer core out to
    # 330 ± 20 km and a solid inner core at 240 ± 10 km — and quote the
    # densities that reproduce the observed Love numbers, 5.1 and 8.0 g/cm³.
    #   crust  4π(1737.4 km)² × 38.5 km = 1.460e18 m³ × 2550 = 3.72e21 kg → 0.051
    #   inner  (4/3)π(240 km)³ × 8000                                    → 0.0063
    #   outer  the 90 km between 330 and 240 × 5100                      → 0.0064
    #   mantle the remainder                                             → 0.936
    # Weber's two pieces together come to 0.013 against the 0.016 that Garcia's
    # single 380 km core gives, so the two seismic results agree on "the Moon
    # is between one and two percent metal" and disagree on nothing that shows.
    # Between the core and 480 ± 15 km sits a partially molten boundary layer,
    # still mantle rock, folded into the mantle here.
    "naif-301": BodyInterior(
        structure="differentiated",
        structure_source="weber_2011",
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
                mass_fraction=0.936,
                composition=(Component(SILICATE, 1.0, "garcia_2011"),),
                source="garcia_2011",
                outer_radius_km=1698.9,
                derived=True,
            ),
            Layer(
                role="outer_core",
                mass_fraction=0.0064,
                composition=(Component(METAL, 1.0, "weber_2011"),),
                source="weber_2011",
                outer_radius_km=330.0,
                derived=True,
            ),
            Layer(
                role="inner_core",
                mass_fraction=0.0063,
                composition=(Component(METAL, 1.0, "weber_2011"),),
                source="weber_2011",
                outer_radius_km=240.0,
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
                mass_fraction_range=(0.55, 0.67),
                composition=(Component(SILICATE, 1.0, "iess_2014"),),
                source="iess_2014",
                outer_radius_km=191.0,
                derived=True,
                note="from_moment_of_inertia",
            ),
        ),
    ),
    # Io. Galileo's four flybys give R = 1821.6 km, ρ̄ = 3527.8 kg/m³ and
    # C/MR² = 0.37685 — far enough below 0.4 that Io must have a metal core,
    # but mean density and one moment of inertia are two constraints against a
    # three-layer model's four unknowns, so the core's size rides on its
    # composition. The paper's families put it at 550-900 km for Fe-FeS and
    # 350-650 km for Fe, which spans 0.02-0.18 of Io's mass:
    #   (4/3)π(725 km)³ = 1.596e18 m³ × 5150 = 8.22e21 kg / 8.932e22 = 0.092
    # The midpoint of the Fe-FeS range is what ships; the crust and partially
    # molten asthenosphere the paper also expects cannot be separated from the
    # mantle by gravity, so they are not layers here.
    "naif-501": BodyInterior(
        structure="differentiated",
        structure_source="anderson_2001_io",
        layers=(
            Layer(
                role="mantle",
                mass_fraction=0.908,
                composition=(Component(SILICATE, 1.0, "anderson_2001_io"),),
                source="anderson_2001_io",
                outer_radius_km=1821.6,
                derived=True,
                note="from_moment_of_inertia",
            ),
            Layer(
                role="core",
                mass_fraction=0.092,
                mass_fraction_range=(0.016, 0.176),
                composition=(Component(METAL, 1.0, "anderson_2001_io"),),
                source="anderson_2001_io",
                outer_radius_km=725.0,
                derived=True,
                note="core_size_disputed",
            ),
        ),
    ),
    # Europa. Galileo pins C/MR² = 0.346, which with the mean density fixes how
    # much of Europa is water and nothing else: Hussmann's two-layer fit — a
    # 160 km H₂O shell at 920 kg/m³ over a 1405 km interior at 3780 — reproduces
    # that moment of inertia exactly, and gives
    #   shell (4/3)π(1565³ - 1405³) km³ = 4.438e18 m³ × 920 = 4.08e21 kg → 0.085
    # Anderson argues the interior is differentiated further, into a rock mantle
    # and a metallic core, because a well-mixed rock-metal Europa would have to
    # be 12% richer in iron than Io. But the gravity cannot size that core, and
    # the 3780 kg/m³ the moment of inertia demands is already denser than
    # silicate alone — so the metal is inside this layer rather than beside it.
    "naif-502": BodyInterior(
        structure="differentiated",
        structure_source="anderson_1998",
        note="subsurface_ocean",
        layers=(
            # Ice or ocean: their densities are too close for gravity to tell
            # apart, so this is one layer of water in whatever phase.
            Layer(
                role="ice_shell",
                mass_fraction=0.085,
                composition=(Component(WATER, 1.0, "anderson_1998"),),
                source="hussmann_2006",
                outer_radius_km=1565.0,
                derived=True,
            ),
            Layer(
                role="core",
                mass_fraction=0.915,
                composition=(Component(SILICATE, 1.0, "anderson_1998"),),
                source="hussmann_2006",
                outer_radius_km=1405.0,
                derived=True,
                note="core_size_disputed",
            ),
        ),
    ),
    # Ganymede, the most centrally condensed solid body in the Solar System:
    # C/MR² = 0.3105 against 0.334 for Earth. Three layers, four unknowns and
    # two constraints again, so the paper reports a family — an Fe-FeS core of
    # 0.2-0.5 R with 2-33% of the mass, ice at 1000-1350 kg/m³, and the ice-rock
    # interface between 0.53 and 0.73 R. Fixing the two densities the paper
    # calls most reasonable (1100 for the ice, 3300 for the silicates alone)
    # leaves exactly one member of that family, and it is the one that ships:
    #   core   770 km (0.29 R) at 5150 → 0.067
    #   mantle out to 1872 km (0.71 R) at 3300 → 0.569
    #   ice    the outer 762 km at 1100 → 0.364
    # It reproduces ρ̄ = 1936 kg/m³ and C/MR² = 0.3105 to five figures and lands
    # inside every range the paper quotes, including its own "~800 km" ice shell.
    "naif-503": BodyInterior(
        structure="differentiated",
        structure_source="anderson_1996",
        layers=(
            Layer(
                role="ice_shell",
                mass_fraction=0.364,
                composition=(Component(WATER, 1.0, "anderson_1996"),),
                source="anderson_1996",
                outer_radius_km=2634.0,
                derived=True,
            ),
            Layer(
                role="mantle",
                mass_fraction=0.569,
                composition=(Component(SILICATE, 1.0, "anderson_1996"),),
                source="anderson_1996",
                outer_radius_km=1872.0,
                derived=True,
                note="from_moment_of_inertia",
            ),
            Layer(
                role="core",
                mass_fraction=0.067,
                mass_fraction_range=(0.02, 0.33),
                composition=(Component(METAL, 1.0, "anderson_1996"),),
                source="anderson_1996",
                outer_radius_km=770.0,
                derived=True,
                note="core_size_disputed",
            ),
        ),
    ),
    # Callisto, the one that never finished. C/MR² = 0.3549 is below 0.4 but
    # above the 0.38 of an undifferentiated Callisto, so rock sank — but not
    # far enough: every model consistent with the data keeps ice and rock mixed
    # to a depth of at least 1000 km. The paper prefers a clean ice shell over a
    # uniform ice-rock interior; solving that two-layer case for the observed
    # moment of inertia at an ice density of 1000 kg/m³ gives
    #   shell    320 km thick → 0.190 of the mass, all water
    #   interior 2280 kg/m³, which is half ice and half rock-metal by volume
    #            when the rock is bulk Io at 3560 → 0.78 rock, 0.22 water by mass
    # Whole-body that is 63% rock, the same answer a plain two-component mass
    # balance on the mean density gives, so the split survives the model.
    "naif-504": BodyInterior(
        structure="partially_differentiated",
        structure_source="anderson_2001_callisto",
        layers=(
            Layer(
                role="ice_shell",
                mass_fraction=0.190,
                composition=(Component(WATER, 1.0, "anderson_2001_callisto"),),
                source="anderson_2001_callisto",
                outer_radius_km=2410.3,
                derived=True,
            ),
            Layer(
                role="bulk",
                mass_fraction=0.810,
                composition=(
                    Component(SILICATE, 0.78, "anderson_2001_callisto"),
                    Component(WATER, 0.22, "anderson_2001_callisto"),
                ),
                source="anderson_2001_callisto",
                outer_radius_km=2090.0,
                derived=True,
                note="from_moment_of_inertia",
            ),
        ),
    ),
    # Titan. Cassini's tidal Love number k₂ ≈ 0.6 is an order of magnitude
    # above what a solid body of Titan's size could manage, so some global
    # layer inside it deforms like a fluid on a 16-day timescale — an ocean.
    # The end-of-mission gravity solution adds the piece k₂ alone could not
    # give: J₂ and C₂₂ put the moment of inertia at 0.341, which with R = 2575
    # km and ρ̄ = 1881 kg/m³ closes a two-layer model. Solving mass and moment
    # of inertia together for an H₂O layer at 1000 kg/m³:
    #   881 f² = 0.341ρ̄/0.4 - 1000 → f = 0.828, so the core is 2131 km at
    #   2554 kg/m³ under 444 km of water → core 0.770, hydrosphere 0.230
    # The paper quotes the same model as "~400 km" thick over a core "around
    # 2500 kg/m³"; the numbers here are the exact solution of it.
    #
    # One H₂O layer, not three: ice I, the ocean and the high-pressure ice
    # below it are close enough in density that gravity never separates them.
    # And 2554 kg/m³ is far too light for dry rock, so the core is hydrated or
    # porous or both — the same story as Enceladus, one order of magnitude up.
    "naif-606": BodyInterior(
        structure="differentiated",
        structure_source="iess_2012",
        note="subsurface_ocean",
        layers=(
            Layer(
                role="ice_shell",
                mass_fraction=0.230,
                composition=(Component(WATER, 1.0, "durante_2019"),),
                source="durante_2019",
                outer_radius_km=2575.0,
                derived=True,
            ),
            Layer(
                role="core",
                mass_fraction=0.770,
                composition=(Component(SILICATE, 1.0, "durante_2019"),),
                source="durante_2019",
                outer_radius_km=2131.0,
                derived=True,
                note="hydrated_rock",
            ),
        ),
    ),
    # Vesta, the only asteroid with a measured metal core. Dawn's gravity plus
    # the HED meteorites give the paper's most-differentiated end member: a
    # 110 km core at 7800 kg/m³ under a 40 km basaltic crust at 2700, and the
    # olivine mantle falls out of the arithmetic at 3400 kg/m³, which is the
    # density petrology independently expects.
    #   core  (4/3)π(110 km)³ = 5.575e15 m³ × 7800 = 4.35e19 kg / 2.591e20 → 0.168
    #   crust the outer 40 km of a 261.7 km sphere × 2700               → 0.307
    # Sulphur in the core would lower its density and widen it: at 6000 kg/m³
    # the core is 138 km and a quarter of Vesta's mass.
    "spkid-20000004": BodyInterior(
        structure="differentiated",
        structure_source="ermakov_2014",
        layers=(
            Layer(
                role="crust",
                mass_fraction=0.307,
                composition=(Component(SILICATE, 1.0, "ermakov_2014"),),
                source="ermakov_2014",
                outer_radius_km=261.7,
                derived=True,
            ),
            Layer(
                role="mantle",
                mass_fraction=0.525,
                composition=(Component(SILICATE, 1.0, "ermakov_2014"),),
                source="ermakov_2014",
                outer_radius_km=221.7,
                derived=True,
            ),
            Layer(
                role="core",
                mass_fraction=0.168,
                mass_fraction_range=(0.168, 0.255),
                composition=(Component(METAL, 1.0, "ermakov_2014"),),
                source="ermakov_2014",
                outer_radius_km=110.0,
                derived=True,
                note="core_size_disputed",
            ),
        ),
    ),
    # Ceres, which got part of the way. Dawn's gravity and shape need a density
    # gradient but not a rock core: the deepest interior is CM-chondrite-like
    # rather than dehydrated silicate, so what separated was the volatiles, not
    # the metal. Taking the paper's CM end member — a 280 km core at 2900 kg/m³
    # under a 190 km shell at 1950 —
    #   core  (4/3)π(280 km)³ = 9.195e16 m³ × 2900 = 2.67e20 kg → 0.285
    #   shell the outer 190 km × 1950                          → 0.715
    # (normalised: the two-layer model comes to 2158 kg/m³ against 2162 observed)
    # and the shell's 1950 is 48% ice by volume between that same rock and pure
    # ice, so 23% of the shell is free water. The bound water inside the rock —
    # a CM chondrite is roughly a tenth water by mass — is real but unquantified
    # here, so this understates how wet Ceres is.
    "naif-2000001": BodyInterior(
        structure="partially_differentiated",
        structure_source="park_2016",
        layers=(
            Layer(
                role="crust",
                mass_fraction=0.715,
                composition=(
                    Component(SILICATE, 0.77, "park_2016"),
                    Component(WATER, 0.23, "park_2016"),
                ),
                source="park_2016",
                outer_radius_km=470.0,
                derived=True,
            ),
            Layer(
                role="core",
                mass_fraction=0.285,
                composition=(Component(SILICATE, 1.0, "park_2016"),),
                source="park_2016",
                outer_radius_km=280.0,
                derived=True,
                note="hydrated_rock",
            ),
        ),
    ),
    # Dione. Cassini's three gravity flybys give J₂/C₂₂ = 4.10, far enough from
    # the hydrostatic 10/3 that the moment of inertia cannot be read straight
    # off the gravity — but far enough from an undifferentiated body's 0.4 that
    # rock has clearly sunk. Fitting shape and gravity together prefers a core
    # of 400 ± 25 km at 2400 ± 200 kg/m³ under a water-ice envelope:
    #   (4/3)π(400 km)³ = 2.681e17 m³ × 2400 = 6.43e20 kg / 1.111e21 = 0.58
    # The paper's own band across the plausible moments of inertia is 56-66%,
    # so the rock:ice ratio is close to 1:1 by mass. The topography only
    # balances if the ice shell floats on something denser and softer, which is
    # why the ocean is here — it is inside this one H₂O layer, not weighable
    # apart from it. Supersedes the two-layer thermal model below.
    "naif-604": BodyInterior(
        structure="differentiated",
        structure_source="zannoni_2020",
        note="subsurface_ocean",
        layers=(
            Layer(
                role="ice_shell",
                mass_fraction=0.42,
                composition=(Component(WATER, 1.0, "zannoni_2020"),),
                source="zannoni_2020",
                outer_radius_km=564.1,
                derived=True,
            ),
            Layer(
                role="core",
                mass_fraction=0.58,
                mass_fraction_range=(0.56, 0.66),
                composition=(Component(SILICATE, 1.0, "zannoni_2020"),),
                source="zannoni_2020",
                outer_radius_km=400.0,
                derived=True,
            ),
        ),
    ),
    # Uranus and Neptune, and the reason `heavy_elements` exists. Fitting the
    # observed gravity gives the mass of everything above helium, but not what
    # it is: model it as rock and Uranus is 75.7% heavy elements, model it as
    # ice and the same planet is 88.6%, and both fit the pressure-density
    # curve equally well. Reality is a mixture, so the value shipped is the
    # midpoint and the range is the two end-member models.
    #
    # There is no boundary to draw. Z climbs continuously from ~0.007 at the
    # surface to ~0.82 at the centre, with the steepening starting around
    # 1500 K — which is where silicates begin to vaporise, a suspiciously good
    # coincidence. One `bulk` layer, marked diffuse, is the honest shape.
    "naif-799": BodyInterior(
        structure="fluid",
        structure_source="helled_2011",
        layers=(
            Layer(
                role="bulk",
                mass_fraction=1.0,
                composition=(
                    Component(HEAVY_ELEMENTS, 0.822, "helled_2011", (0.757, 0.886)),
                    Component(HYDROGEN, 0.133, "helled_2011", (0.085, 0.181)),
                    Component(HELIUM, 0.045, "helled_2011", (0.029, 0.062)),
                ),
                source="helled_2011",
                outer_radius_km=25362.0,
                diffuse=True,
            ),
        ),
    ),
    # Neptune runs the same models to nearly the same answer — the two planets
    # differ less in composition than in anything else about them. The one
    # asymmetry the fits do find is that Neptune needs a non-solar envelope
    # where Uranus is matched by a solar one.
    "naif-899": BodyInterior(
        structure="fluid",
        structure_source="helled_2011",
        layers=(
            Layer(
                role="bulk",
                mass_fraction=1.0,
                composition=(
                    Component(HEAVY_ELEMENTS, 0.826, "helled_2011", (0.758, 0.893)),
                    Component(HYDROGEN, 0.130, "helled_2011", (0.080, 0.181)),
                    Component(HELIUM, 0.044, "helled_2011", (0.027, 0.062)),
                ),
                source="helled_2011",
                outer_radius_km=24622.0,
                diffuse=True,
            ),
        ),
    ),
    # The Sun. Two zones with measured compositions and no masses: this source
    # is a solar model paper, and it tabulates abundances and the depth of the
    # convective zone but not how the Sun's mass divides between them, so the
    # layers here carry geometry and chemistry only.
    #
    # The interesting number is what 4.6 Gyr of fusion has done. The
    # convective zone is stirred well enough that its surface abundances are
    # the whole zone's — hydrogen 0.740, helium 0.243 — while at the centre
    # helium has gone from the 0.2725 the Sun formed with to 0.634, more than
    # doubling. Between them lies the radiative zone, which is not a layer
    # here because it is the gradient between the two rather than a third
    # composition; helioseismology puts its top at 0.713 ± 0.001 R☉ against
    # this model's 0.7138, one of the better agreements in the subject.
    "naif-10": BodyInterior(
        structure="fluid",
        structure_source="bahcall_2005",
        layers=(
            Layer(
                role="convective_zone",
                mass_fraction=None,
                composition=(
                    Component(HYDROGEN, 0.740, "bahcall_2005"),
                    Component(HELIUM, 0.243, "bahcall_2005"),
                    Component(HEAVY_ELEMENTS, 0.017, "bahcall_2005"),
                ),
                source="bahcall_2005",
                outer_radius_km=695700.0,
            ),
            Layer(
                role="core",
                mass_fraction=None,
                composition=(
                    Component(HELIUM, 0.634, "bahcall_2005"),
                    Component(HYDROGEN, 0.346, "bahcall_2005"),
                    Component(HEAVY_ELEMENTS, 0.020, "bahcall_2005"),
                ),
                source="bahcall_2005",
            ),
        ),
    ),
    # Pluto, Charon and Triton, from the review that reads them side by side.
    # None of the three has a measured moment of inertia, so the split is the
    # two-layer mass balance on bulk density — 1/ρ̄ = fₛ/ρₛ + (1-fₛ)/ρᵢ against
    # chondritic rock at 3.5 g/cc and a hydrosphere at 0.95 — and the rock
    # fractions are quoted from that table rather than recomputed here.
    #
    # They are rock-rich for their size: 2:1 or 3:1 rock to ice, against the
    # 2:3 the solar nebula would give if every ice former condensed. Locking
    # oxygen up as CO rather than in silicates is the way out.
    #
    # A metal core is expected on theoretical grounds for all three and
    # observed on none, so the core stays undivided rock.
    "naif-999": BodyInterior(
        structure="differentiated",
        structure_source="nimmo_2025",
        # An undifferentiated Pluto would have turned its deep ice to ice II as
        # it cooled and contracted; the surface is almost entirely extensional
        # instead. That is the strongest evidence any of the three has. The
        # ocean is a weaker case — extensional tectonics, cryovolcanism, no
        # fossil bulge and where Sputnik Planitia sits are each consistent with
        # one without requiring it.
        note="subsurface_ocean",
        layers=(
            Layer(
                role="ice_shell",
                mass_fraction=0.32,
                composition=(Component(WATER, 1.0, "nimmo_2025"),),
                source="nimmo_2025",
                outer_radius_km=1188.3,
                note="from_bulk_density",
            ),
            Layer(
                role="core",
                mass_fraction=0.68,
                composition=(Component(SILICATE, 1.0, "nimmo_2025"),),
                source="nimmo_2025",
                outer_radius_km=840.0,
                note="from_bulk_density",
            ),
        ),
    ),
    # Charon is in that table for comparison rather than as its own result, and
    # is the one body of the three thought to have frozen through: it may have
    # had an ocean once but is unlikely to now.
    "naif-901": BodyInterior(
        structure="differentiated",
        structure_source="nimmo_2025",
        layers=(
            Layer(
                role="ice_shell",
                mass_fraction=0.38,
                composition=(Component(WATER, 1.0, "nimmo_2025"),),
                source="nimmo_2025",
                outer_radius_km=606.0,
                note="from_bulk_density",
            ),
            Layer(
                role="core",
                mass_fraction=0.62,
                composition=(Component(SILICATE, 1.0, "nimmo_2025"),),
                source="nimmo_2025",
                outer_radius_km=412.0,
                note="from_bulk_density",
            ),
        ),
    ),
    # The four giants and the Sun deliberately carry no `no_solid_surface`
    # note. `structure="fluid"` already renders as "no solid surface" on the
    # panel, and their atmosphere blocks carry the fuller version of the same
    # sentence — the one that also explains why the pressures are quoted at a
    # cloud deck. Three statements of one fact stacked down the panel is what
    # it looked like.
    #
    # Jupiter. Juno's gravity harmonics need more heavy elements than a clean
    # core-plus-envelope allows, and the way they fit is a *dilute* core: the
    # heavy elements are not a ball with a surface but a smear reaching a
    # substantial fraction of the radius, mixed into hydrogen the whole way.
    # That is what `diffuse` is for — the radius below is where the enrichment
    # fades out, not where anything ends. The core carries 7-25 M⊕ of heavy
    # elements against Jupiter's 317.83 M⊕, so 0.022-0.079 of the planet, and
    # nothing in the data prefers a point inside that.
    #
    # The envelope composition is the one thing here that was measured rather
    # than modelled: the Galileo probe fell through it and read Y = 0.2333,
    # Z = 0.0169. That is the molecular envelope only — the metallic envelope
    # below it is Z-enriched over that, which is why the whole-planet heavy
    # element mass comes to 24-27 M⊕, more than this bar's 0.066 implies.
    "naif-599": BodyInterior(
        structure="fluid",
        structure_source="wahl_2017",
        layers=(
            Layer(
                role="envelope",
                mass_fraction=0.950,
                mass_fraction_range=(0.921, 0.978),
                composition=(
                    Component(HYDROGEN, 0.750, "wahl_2017"),
                    Component(HELIUM, 0.233, "wahl_2017"),
                    Component(HEAVY_ELEMENTS, 0.017, "wahl_2017"),
                ),
                source="wahl_2017",
                outer_radius_km=71492.0,
            ),
            Layer(
                role="core",
                mass_fraction=0.050,
                mass_fraction_range=(0.022, 0.079),
                composition=(Component(HEAVY_ELEMENTS, 1.0, "wahl_2017"),),
                source="wahl_2017",
                diffuse=True,
            ),
        ),
    ),
    # Saturn, from the Grand Finale orbits. The gravity rules out uniform
    # rotation outright, and once differential rotation is in the models the
    # core lands at 15.0-18.2 M⊕ of Saturn's 95.16 — 0.158-0.191 — inside a
    # fractional radius of 0.19-0.23.
    #
    # The envelope's helium is the loose end. Infrared measurements of the
    # atmosphere go as low as Y = 0.055 against a protosolar 0.274, because
    # helium rains out of the molecular envelope and pools deeper. Helium does
    # not escape a planet, though, so averaged over the whole envelope
    # protosolar is the right figure and the depletion is a redistribution
    # inside this layer, not a loss from it.
    "naif-699": BodyInterior(
        structure="fluid",
        structure_source="iess_2019",
        layers=(
            Layer(
                role="envelope",
                mass_fraction=0.825,
                mass_fraction_range=(0.809, 0.842),
                composition=(
                    Component(HYDROGEN, 0.687, "iess_2019"),
                    Component(HELIUM, 0.274, "iess_2019", (0.055, 0.274)),
                    Component(HEAVY_ELEMENTS, 0.039, "iess_2019", (0.017, 0.061)),
                ),
                source="iess_2019",
                outer_radius_km=58232.0,
            ),
            Layer(
                role="core",
                mass_fraction=0.175,
                mass_fraction_range=(0.158, 0.191),
                composition=(Component(HEAVY_ELEMENTS, 1.0, "iess_2019"),),
                source="iess_2019",
                outer_radius_km=12229.0,
            ),
        ),
    ),
    # Triton has almost no observational constraint on its interior — its shape
    # permits nearly anything and its surface is 10 Myr old, so nothing early
    # survives. The theory is strong instead: capture into a near-unity
    # eccentricity and the tidal circularisation that followed release enough
    # heat to raise the whole body by of order 10,000 K, which melts and
    # separates it completely. Its slightly higher rock fraction may be what
    # that heating boiled off. No ocean note: the young surface implies high
    # heat flow, which is suggestive and nothing more.
    "naif-801": BodyInterior(
        structure="differentiated",
        structure_source="nimmo_2025",
        layers=(
            Layer(
                role="ice_shell",
                mass_fraction=0.25,
                composition=(Component(WATER, 1.0, "nimmo_2025"),),
                source="nimmo_2025",
                outer_radius_km=1353.4,
                note="from_bulk_density",
            ),
            Layer(
                role="core",
                mass_fraction=0.75,
                composition=(Component(SILICATE, 1.0, "nimmo_2025"),),
                source="nimmo_2025",
                outer_radius_km=1028.0,
                note="from_bulk_density",
            ),
        ),
    ),
}


# The medium-sized icy satellites, where the only constraint anyone has is the
# mean density. Hussmann et al. solve a two-layer body — rock core at 3500
# kg/m³ under an ice shell — against each satellite's density and its
# radiogenic heat budget, and tabulate the resulting core mass fraction. That
# is inference from bulk density and nothing more, which is what the note key
# says; the split is worth about the two figures given here.
#
# Nine of the paper's rows are not used here, each because something better
# came along: Enceladus and Dione were flown close enough for Cassini to weigh
# properly, Pluto and Charon were sized properly by New Horizons (the radii
# this paper used are ~4% small, which inflates the density it fitted and so
# the rock fraction it reports, 0.72 against 0.68 for Pluto), and the five
# Uranian moons are redone below on post-Voyager masses.
#
# Rhea is the row to treat most carefully. Cassini's second gravity flyby put
# J₂/C₂₂ at 3.91, off hydrostatic, so the measured gravity does not resolve
# whether Rhea is differentiated at all — models from near-homogeneous
# (C/MR² = 0.399) to well separated (0.335) all fit. The 0.27 below is what a
# thermal model gives if you assume it separated, which is what the note says.
#
# (object_id, satellite radius km, core radius km, core mass fraction)
_ICY_TWO_LAYER: tuple[tuple[str, float, float, float], ...] = (
    ("naif-601", 198.8, 78.1, 0.18),  # Mimas
    ("naif-605", 764.5, 347.2, 0.27),  # Rhea
    ("naif-608", 734.5, 242.9, 0.12),  # Iapetus
)

INTERIOR_FACTS.update(
    {
        object_id: BodyInterior(
            structure="differentiated",
            structure_source="hussmann_2006",
            layers=(
                Layer(
                    role="ice_shell",
                    mass_fraction=round(1.0 - core, 2),
                    composition=(Component(WATER, 1.0, "hussmann_2006"),),
                    source="hussmann_2006",
                    outer_radius_km=radius_km,
                    note="from_bulk_density",
                ),
                Layer(
                    role="core",
                    mass_fraction=core,
                    composition=(Component(SILICATE, 1.0, "hussmann_2006"),),
                    source="hussmann_2006",
                    outer_radius_km=core_radius_km,
                    note="from_bulk_density",
                ),
            ),
        )
        for object_id, radius_km, core_radius_km, core in _ICY_TWO_LAYER
    }
)

# The five Uranian moons, same two-layer idea but on Jacobson's post-Voyager
# masses rather than the ones available in 2006, and with the core radius
# solved for directly against an ice shell at 920 kg/m³ and a rock core at
# 3500. Recomputing the core mass from each quoted radius reproduces the
# paper's own shell densities to within 4 kg/m³, which is the check that the
# arithmetic here matches theirs:
#   (4/3)π(Rc)³ × 3500 / M
# The mass revisions move things: Umbriel goes from 0.40 to 0.58 and Ariel the
# other way, 0.56 to 0.50. Whether any of them still has an ocean is left
# open — Titania and Oberon could, but only with ice-shell porosity or ammonia
# to slow the freezing, and the smaller three cannot on radiogenic heat alone.
# A 2500 kg/m³ Enceladus-like core instead of 3500 would push each core radius
# out by roughly 100 km, which is what the note is warning about.
#
# (object_id, satellite radius km, core radius km, core mass fraction)
_URANIAN_TWO_LAYER: tuple[tuple[str, float, float, float], ...] = (
    ("naif-701", 578.9, 342.0, 0.497),  # Ariel
    ("naif-702", 584.7, 375.0, 0.576),  # Umbriel
    ("naif-703", 788.9, 516.0, 0.596),  # Titania
    ("naif-704", 761.4, 493.0, 0.586),  # Oberon
    ("naif-705", 235.8, 100.0, 0.239),  # Miranda
)

INTERIOR_FACTS.update(
    {
        object_id: BodyInterior(
            structure="differentiated",
            structure_source="bierson_2022",
            layers=(
                Layer(
                    role="ice_shell",
                    mass_fraction=round(1.0 - core, 3),
                    composition=(Component(WATER, 1.0, "bierson_2022"),),
                    source="bierson_2022",
                    outer_radius_km=radius_km,
                    derived=True,
                    note="from_bulk_density",
                ),
                Layer(
                    role="core",
                    mass_fraction=core,
                    composition=(Component(SILICATE, 1.0, "bierson_2022"),),
                    source="bierson_2022",
                    outer_radius_km=core_radius_km,
                    derived=True,
                    note="from_bulk_density",
                ),
            ),
        )
        for object_id, radius_km, core_radius_km, core in _URANIAN_TWO_LAYER
    }
)

# Tethys is the exception in that table: at 984 kg/m³ it is very nearly a ball
# of water ice, the model returns a 29 km core carrying 0.06% of the mass, and
# the paper says outright that assuming it differentiated at all is
# questionable. So it ships as one undifferentiated body rather than a shell
# around a pebble.
INTERIOR_FACTS["naif-603"] = BodyInterior(
    structure="undifferentiated",
    structure_source="hussmann_2006",
    layers=(
        Layer(
            role="bulk",
            mass_fraction=1.0,
            composition=(
                Component(WATER, 0.999, "hussmann_2006"),
                Component(SILICATE, 0.001, "hussmann_2006"),
            ),
            source="hussmann_2006",
            outer_radius_km=531.0,
            note="from_bulk_density",
        ),
    ),
)
