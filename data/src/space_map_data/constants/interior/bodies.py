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


# The base of a floating ice shell is a phase boundary rather than a modelled
# temperature: it sits on the melting curve of ice I, which runs from 273 K at
# low pressure down to 251 K at the ice I-III triple point, and lower again
# where the ocean is salty. Every ocean world gets the same bracket because it
# is the same curve — Vance's models span it end to end across the five moons
# they cover — and no shell thickness is known well enough to say where on it a
# given body sits.
ICE_OCEAN_INTERFACE_K = (250.0, 273.0)


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
    # 2020 ± 30 used above — and finds a solid inner core at γ = 0.517 ± 0.170
    # of that radius:
    #   (4/3)π(0.517 × 1985 km)³ × 8000 = 3.62e22 kg / 3.3011e23 = 0.110
    # which leaves 0.599 for the liquid outer core, and that then has to
    # average 6595 kg/m³ against the whole core's 6778 — the light elements
    # sitting in the liquid, as they do on Earth. γ's ±0.170 cubes into 0.033
    # to 0.257 of the planet, which is what ships as the range: the inner core
    # is there and its size is barely known.
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
                state="solid",
            ),
            Layer(
                role="mantle",
                mass_fraction=0.269,
                composition=(Component(SILICATE, 1.0, "hauck_2013"),),
                source="hauck_2013",
                outer_radius_km=2404.7,
                derived=True,
                note="from_moment_of_inertia",
                # Reconstructed from MESSENGER's northern-plains lavas by
                # putting the melt back together with the enstatite and
                # forsterite left behind. FeO of 0.02 wt% is the number worth
                # noticing: Mercury's rock is iron-free to a part in a
                # thousand, because Mercury assembled reduced enough that
                # essentially every atom of iron went to the core.
                detail=Detail(
                    unit=OXIDE_WEIGHT,
                    entries=(
                        ("SiO2", 0.5367),
                        ("MgO", 0.3689),
                        ("Al2O3", 0.0457),
                        ("CaO", 0.0226),
                        ("TiO2", 0.0024),
                    ),
                    source="nittler_2018",
                ),
                state="solid",
            ),
            # Fe-S-Si. A solid FeS layer may also float at the top of the
            # liquid core; that one stays out, being something the gravity
            # allows rather than anything it finds.
            Layer(
                role="outer_core",
                mass_fraction=0.599,
                mass_fraction_range=(0.452, 0.676),
                composition=(Component(METAL, 1.0, "hauck_2013"),),
                source="hauck_2013",
                outer_radius_km=2020.0,
                derived=True,
                state="liquid",
                # Hauck's 1475-1825 C at the core-mantle boundary, which is
                # what Mercury's models constrain; the centre is hotter by an
                # adiabat nobody has pinned.
                outer_temperature_range_k=(1750.0, 2100.0),
                temperature_sources=("hauck_2013",),
            ),
            Layer(
                role="inner_core",
                mass_fraction=0.110,
                mass_fraction_range=(0.033, 0.257),
                composition=(Component(METAL, 1.0, "genova_2019"),),
                source="genova_2019",
                outer_radius_km=1026.0,
                derived=True,
                note="core_size_disputed",
                state="solid",
            ),
        ),
    ),
    # Venus, the last terrestrial planet to get a measured moment of inertia:
    # C/MR² = 0.337 ± 0.024, from fifteen years of radar speckle tracking the
    # precession of its spin axis. The paper closes its own two-layer model by
    # borrowing the one number the tidal models agree on — every Dumoulin
    # interior within the plausible C/MR² range has a core density within 1%
    # of 10358 kg/m³ — and solving for the rest against ρ̄ = 5242.8:
    #   core   3508 km (0.580 R) at 10358 → 0.385
    #   mantle the rest at 4006           → 0.615
    # Almost exactly Earth's core radius, in a planet 5% smaller.
    #
    # The ±0.024 on C/MR² is ±500 km on that radius, which is 0.24 to 0.57 of
    # the planet in mass — so "about a third metal" is the whole claim.
    # Whether any of the core is solid is likewise open: the tidal Love number
    # allows a fully solid one once the mantle's anelasticity is accounted for.
    #
    # The crust is Venus's own, not the moment of inertia's: gravity and
    # topography together bound the global mean at 8-25 km, and the 15 km used
    # below is the value that solution is drawn for, at 2800 kg/m³.
    #   4π(6051.8 km)² × 15 km = 6.90e18 m³ × 2800 = 1.93e22 kg → 0.0040
    # A quarter of a percent of the planet, and the thinnest crust of the four
    # terrestrial planets by some way.
    "naif-299": BodyInterior(
        structure="differentiated",
        structure_source="margot_2021",
        layers=(
            Layer(
                role="crust",
                mass_fraction=0.0040,
                mass_fraction_range=(0.0021, 0.0066),
                composition=(Component(SILICATE, 1.0, "james_2013"),),
                source="james_2013",
                outer_radius_km=6051.8,
                derived=True,
                state="solid",
            ),
            Layer(
                role="mantle",
                mass_fraction=0.611,
                composition=(Component(SILICATE, 1.0, "dumoulin_2017"),),
                source="margot_2021",
                outer_radius_km=6036.8,
                derived=True,
                note="from_moment_of_inertia",
                state="solid",
            ),
            Layer(
                role="core",
                mass_fraction=0.385,
                mass_fraction_range=(0.243, 0.574),
                composition=(Component(METAL, 1.0, "dumoulin_2017"),),
                source="margot_2021",
                outer_radius_km=3508.0,
                derived=True,
                note="core_size_disputed",
                # The widest bracket of the four terrestrials, and for the same
                # reason everything else about Venus is wide: no seismometer
                # has ever worked there, so this is a thermal-evolution model
                # anchored on an Earth-like composition.
                outer_temperature_range_k=(4000.0, 5000.0),
                temperature_sources=("dumoulin_2017",),
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
                role="crust",
                mass_fraction=0.0035,
                composition=(Component(SILICATE, 1.0, "taylor_mclennan_2009"),),
                source="taylor_mclennan_2009",
                outer_radius_km=6371.0,
                note="continental_crust_only",
                # Table 11.3's bulk continental crust, and with it that
                # chapter's 41 km average thickness and 0.35% of Earth's mass.
                # The oceanic crust is a fifth of the volume and none of these
                # numbers; a global mean would have to blend the two, and the
                # book gives no oceanic density to blend with.
                detail=Detail(
                    unit=OXIDE_WEIGHT,
                    entries=(
                        ("SiO2", 0.574),
                        ("Al2O3", 0.159),
                        ("FeO", 0.0912),
                        ("CaO", 0.0741),
                        ("MgO", 0.0531),
                        ("Na2O", 0.0311),
                        ("K2O", 0.0132),
                        ("TiO2", 0.0090),
                    ),
                    source="taylor_mclennan_2009",
                ),
                state="solid",
            ),
            Layer(
                role="mantle",
                mass_fraction=0.6733,
                composition=(Component(SILICATE, 1.0, "mcdonough_1995"),),
                source="mcdonough_2003",
                outer_radius_km=6330.0,
                # Bulk silicate Earth, the pyrolite model, which is mantle plus
                # crust. The crust it includes is half a percent of that mass,
                # so it moves no digit here.
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
                state="solid",
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
                state="liquid",
                # A spread across experiments rather than an error bar: the
                # pyrolite solidus bounds it from above at 3570 ± 200 K, and
                # iron melting curves and later solidus work land either side.
                # No experiment prefers a number the others do not contest.
                outer_temperature_range_k=(3400.0, 4200.0),
                temperature_sources=("nomura_2014",),
            ),
            Layer(
                role="inner_core",
                mass_fraction=0.0162,
                composition=(Component(METAL, 1.0, "mcdonough_2003"),),
                source="mcdonough_2003",
                outer_radius_km=1221.5,
                state="solid",
                # The one boundary in any planet fixed by a phase change we can
                # reproduce: the inner core ends where iron freezes. Pure iron
                # melts at 6230 ± 500 K at that pressure and the light elements
                # in the alloy depress it by ~700 K.
                outer_temperature_k=5500.0,
                outer_temperature_range_k=(5000.0, 6000.0),
                temperature_sources=("anzellini_2013",),
            ),
        ),
    ),
    # Mars, and a core that got smaller after everyone had finished quoting it.
    # InSight's first answer put the core-mantle boundary at 1830 ± 40 km with
    # a mean density of 5.7-6.3 g/cm³ — a core too light for any plausible
    # iron alloy, needing a quarter of its weight in sulphur and friends. Two
    # groups resolved that in 2023 the same way and independently: the
    # reflector at 1830 km is not the core, it is the top of a *fully molten
    # silicate layer* lying on it. Below that the core proper is 1675 ± 30 km
    # at 6.65 g/cm³ (Samuel's is 1650 ± 20), which is a normal iron alloy.
    #   core   (4/3)π(1675 km)³ = 1.968e19 m³ × 6650 = 1.309e23 → 0.204
    #   molten the 150 ± 15 km above it at 4050              → 0.037
    #   mantle the remainder                                 → 0.729
    # The crust is untouched by any of this.
    #
    # Not settled. The layer rests on one diffracted arrival from one impact,
    # a re-reading of the phase that gave 1830 km rather than a new
    # observation, and Breuer's review finds it hard to reconcile with the
    # thin thermal lithosphere Mars Global Surveyor's induction data want. The
    # 2025 seismic detection of an inner core reads the outer core boundary
    # back at 1799 ± 66 km, which agrees with the layer's top rather than with
    # 1675. Hence `core_size_disputed` and a range spanning both.
    #
    # That inner core is the other new layer: PKKP and PKiKP arrivals put it at
    # 613 ± 67 km with a ~7% density jump across the boundary, which at a fixed
    # total core mass is
    #   inner (4/3)π(613 km)³ × 7091 = 6.84e21 kg → 0.011, outer → 0.193
    # Mars is the third body known to have one, after Earth and Mercury.
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
                # Basalt, and not much else: the whole crust averages close to
                # a single tholeiitic lava. Assembled from rover and orbiter
                # measurements rather than from one instrument — major elements
                # off S- and Cl-free soil and dust corrected for a meteoritic
                # component, cross-checked against Odyssey's gamma-ray maps.
                detail=Detail(
                    unit=OXIDE_WEIGHT,
                    entries=(
                        ("SiO2", 0.493),
                        ("FeO", 0.182),
                        ("Al2O3", 0.105),
                        ("MgO", 0.0906),
                        ("CaO", 0.0692),
                    ),
                    source="taylor_mclennan_2009",
                ),
                state="solid",
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
                # Bulk silicate Mars, and the same composition InSight's own
                # mantle inversion was run on. Twice Earth's FeO at the same
                # MgO is the difference between the two planets' rock.
                detail=Detail(
                    unit=OXIDE_WEIGHT,
                    entries=(
                        ("SiO2", 0.437),
                        ("MgO", 0.305),
                        ("FeO", 0.181),
                        ("Al2O3", 0.0304),
                        ("CaO", 0.0243),
                    ),
                    source="taylor_2013",
                ),
                state="solid",
            ),
            # Molten rock, not metal: iron-rich silicate at 4.05 ± 0.05 g/cm³,
            # the leftover of a magma ocean that sank and stayed liquid because
            # it collected the heat-producing elements on the way down.
            Layer(
                role="magma",
                mass_fraction=0.037,
                composition=(Component(SILICATE, 1.0, "khan_2023"),),
                source="khan_2023",
                outer_radius_km=1825.0,
                derived=True,
                state="liquid",
            ),
            Layer(
                role="outer_core",
                mass_fraction=0.193,
                mass_fraction_range=(0.193, 0.240),
                composition=(Component(METAL, 1.0, "khan_2023"),),
                source="khan_2023",
                outer_radius_km=1675.0,
                derived=True,
                note="core_size_disputed",
                # 9-15% of the core by weight is light elements — sulphur,
                # carbon, oxygen and hydrogen, computed against the same
                # first-principles alloy that fixes the density. Half what the
                # pre-2023 core needed, which is the point: a core at 6.65
                # g/cm³ no longer has to be improbably dirty to be that light.
                detail=Detail(
                    unit=ELEMENT_WEIGHT,
                    entries=(
                        ("Fe", 0.699),
                        ("S", 0.146),
                        ("Ni", 0.057),
                        ("O", 0.047),
                        ("C", 0.043),
                        ("H", 0.008),
                    ),
                    source="khan_2023",
                ),
                state="liquid",
                # InSight sized and weighed the core; the temperature is the
                # mantle adiabat run down to it rather than anything the
                # seismology sees directly.
                outer_temperature_range_k=(2000.0, 2400.0),
                temperature_sources=("stahler_2021",),
            ),
            Layer(
                role="inner_core",
                mass_fraction=0.011,
                mass_fraction_range=(0.0075, 0.0145),
                composition=(Component(METAL, 1.0, "bi_2025"),),
                source="bi_2025",
                outer_radius_km=613.0,
                derived=True,
                state="solid",
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
    #   melt   the 150 km between 480 ± 15 and 330 × 3400              → 0.0145
    #   mantle the remainder                                             → 0.922
    # Weber's two pieces together come to 0.013 against the 0.016 that Garcia's
    # single 380 km core gives, so the two seismic results agree on "the Moon
    # is between one and two percent metal" and disagree on nothing that shows.
    #
    # The partially molten layer between the core and 480 km is the same rock
    # as the mantle above it, which is why it carries no separate composition —
    # what makes it a layer is that the deep mantle crosses its solidus there.
    # The stacks put 5-30% melt in it depending on whether the liquid sits in
    # pockets or wets the grain boundaries, so `partial_melt` rather than
    # `liquid`, and it is why no deep moonquake has ever been located below it.
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
                # 28% alumina, against 6% for the whole Moon: the highland
                # crust is plagioclase feldspar that floated to the top of a
                # magma ocean, which is why it is bright and why it is the
                # oldest surface anyone has walked on.
                detail=Detail(
                    unit=OXIDE_WEIGHT,
                    entries=(
                        ("SiO2", 0.460),
                        ("Al2O3", 0.280),
                        ("CaO", 0.160),
                        ("FeO", 0.045),
                        ("MgO", 0.045),
                    ),
                    source="taylor_mclennan_2009",
                ),
                state="solid",
            ),
            Layer(
                role="mantle",
                mass_fraction=0.922,
                composition=(Component(SILICATE, 1.0, "garcia_2011"),),
                source="garcia_2011",
                outer_radius_km=1698.9,
                derived=True,
                state="solid",
            ),
            Layer(
                role="mantle",
                mass_fraction=0.0145,
                composition=(Component(SILICATE, 1.0, "garcia_2011"),),
                source="weber_2011",
                outer_radius_km=480.0,
                derived=True,
                state="partial_melt",
            ),
            Layer(
                role="outer_core",
                mass_fraction=0.0064,
                composition=(Component(METAL, 1.0, "weber_2011"),),
                source="weber_2011",
                outer_radius_km=330.0,
                derived=True,
                state="liquid",
                # Fixed by what the seismology sees rather than by a thermal
                # model: the outer core is liquid and the inner one is not, so
                # the boundary sits on the iron-sulphur melting range.
                outer_temperature_range_k=(1600.0, 1900.0),
                temperature_sources=("weber_2011",),
            ),
            Layer(
                role="inner_core",
                mass_fraction=0.0063,
                composition=(Component(METAL, 1.0, "weber_2011"),),
                source="weber_2011",
                outer_radius_km=240.0,
                derived=True,
                state="solid",
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
    # A denser core (3.9 g/cm³) would put the rock at 0.55 instead, so treat
    # two-thirds rock as the middle of a real range, not a measurement.
    #
    # Where the ice ends and the ocean begins is not Iess's to say — the two
    # differ by 8% in density and his gravity solution allowed a 30 km shell
    # over a 31 km ocean only as one of a family. Beuthe closes it from a
    # different direction, by requiring the shell to be isostatic at minimum
    # deviatoric stress, and gets 23 ± 4 km of ice over 38 ± 4 km of water —
    # which agrees with Cassini's libration amplitude, a measurement neither
    # model was fitted to, and which lands the rock at 191.1 km without being
    # asked to. So the boundary moves and the core does not:
    #   shell  23 km of ice at 920            → 0.143
    #   ocean  the 38 km below it at 1000     → 0.196
    #   core   the remainder, 2445 kg/m³      → 0.662
    "naif-602": BodyInterior(
        structure="differentiated",
        structure_source="iess_2014",
        note="subsurface_ocean",
        layers=(
            Layer(
                role="ice_shell",
                mass_fraction=0.143,
                composition=(Component(WATER, 1.0, "iess_2014"),),
                source="beuthe_2016",
                outer_radius_km=252.1,
                derived=True,
                state="solid",
            ),
            Layer(
                role="ocean",
                mass_fraction=0.196,
                composition=(Component(WATER, 1.0, "iess_2014"),),
                source="beuthe_2016",
                outer_radius_km=229.1,
                derived=True,
                state="liquid",
                outer_temperature_range_k=ICE_OCEAN_INTERFACE_K,
                temperature_sources=("vance_2018",),
            ),
            Layer(
                role="core",
                mass_fraction=0.662,
                mass_fraction_range=(0.55, 0.67),
                composition=(Component(SILICATE, 1.0, "iess_2014"),),
                source="iess_2014",
                outer_radius_km=191.1,
                derived=True,
                note="from_moment_of_inertia",
                state="solid",
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
    # The midpoint of the Fe-FeS range is what ships; the crust and the
    # asthenosphere under it cannot be separated from the mantle by gravity —
    # the paper's own models trade a thin low-density crust against a thicker
    # melt-rich layer without preferring either — so they are not layers here.
    #
    # Whether the mantle is *mostly* molten was open for forty years and is
    # not any more. A global magma ocean would make Io deform far more than a
    # solid body does; Juno's two flybys measured the tidal Love number at
    # Re(k₂) = 0.125 ± 0.047, which is the rigid answer. So the mantle carries
    # `partial_melt` — melt is everywhere in it, and nowhere connected into a
    # layer. The 100 TW Io radiates comes out through that melt, not off an
    # ocean.
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
                state="partial_melt",
                state_source="park_2025_io",
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
                state="liquid",
            ),
        ),
    ),
    # Europa, four layers from two measurements and two assumptions. The
    # reanalysis of Galileo's tracking raises C/MR² to 0.3547 ± 0.0024, which
    # with R = 1560.8 km and ρ̄ = 3013 kg/m³ is again two constraints; fixing
    # the ice thickness at Howell's 24.3 km and taking Vance's densities (ice
    # 925, ocean 1030, rock 3300, fcc iron 8000) closes the system, and solving
    # mass balance together with C/MR² = 0.4·Σρᵢ(fᵢ⁵−fᵢ₋₁⁵)/ρ̄ gives
    #   ice    1560.8 → 1536.5 km   0.0141
    #   ocean  1536.5 → 1462.4 km   0.0450
    #   mantle 1462.4 →  460.3 km   0.8728
    #   core          →  460.3 km   0.0681
    # Run against Vance's own inputs instead (R 1565, ρ̄ 2989, C/MR² 0.346) the
    # same solver returns 1449.7 and 507.8 km where his full equation-of-state
    # model returns 1447 and 521 — close enough that the uniform-shell
    # shortcut is not what limits this.
    #
    # 98 km of water is thin against the 135-185 km usually quoted, and that is
    # the iron core doing it: Gomez Casajus notes that adding one pulls the H₂O
    # thickness down by several tens of kilometres from their own core-free
    # 138.7 km, because a dense centre already supplies the concentration the
    # moment of inertia is asking for.
    #
    # Gravity sees none of the boundaries inside the water — ice and ocean are
    # within 10% of each other in density — so the ice shell is a thermal
    # result rather than a measured one. Howell propagates twenty parameters
    # through a steady-state heat balance to a distribution rather than a
    # number: 24.3 km is its mode, the +22.8/−1.5 asymmetry is real, and the
    # tail says a shell under 10 km is the unlikely case, not the default one.
    # The core's size rides entirely on what it is made of: 460 km as pure
    # iron, 641 km at the Fe-FeS eutectic.
    "naif-502": BodyInterior(
        structure="differentiated",
        structure_source="gomez_casajus_2021",
        note="subsurface_ocean",
        layers=(
            Layer(
                role="ice_shell",
                mass_fraction=0.0141,
                mass_fraction_range=(0.0133, 0.0270),
                composition=(Component(WATER, 1.0, "vance_2018"),),
                source="howell_2021",
                outer_radius_km=1560.8,
                derived=True,
                note="shell_thickness_modelled",
                state="solid",
            ),
            Layer(
                role="ocean",
                mass_fraction=0.0450,
                mass_fraction_range=(0.0299, 0.0460),
                composition=(Component(WATER, 1.0, "vance_2018"),),
                source="gomez_casajus_2021",
                outer_radius_km=1536.5,
                derived=True,
                state="liquid",
                outer_temperature_range_k=ICE_OCEAN_INTERFACE_K,
                temperature_sources=("vance_2018",),
            ),
            Layer(
                role="mantle",
                mass_fraction=0.8728,
                composition=(Component(SILICATE, 1.0, "anderson_1998"),),
                source="gomez_casajus_2021",
                outer_radius_km=1462.4,
                derived=True,
                note="from_moment_of_inertia",
                state="solid",
            ),
            Layer(
                role="core",
                mass_fraction=0.0681,
                mass_fraction_range=(0.0681, 0.1185),
                composition=(Component(METAL, 1.0, "vance_2018"),),
                source="gomez_casajus_2021",
                outer_radius_km=460.3,
                derived=True,
                note="core_size_disputed",
            ),
        ),
    ),
    # Ganymede, and a rare case of a newer measurement knowing *less*. Juno's
    # flyby, solved without assuming the degree-2 field is hydrostatic, raises
    # C/MR² from Galileo's 0.3105 ± 0.0028 to 0.3159 ± 0.0052 — a body slightly
    # less concentrated towards its centre than the Galileo analysis implied,
    # and with error bars twice as wide, because dropping the hydrostatic
    # assumption is what those bars were hiding.
    #
    # Same three-layer construction as before — Fe-FeS core at 5150 kg/m³, a
    # silicate mantle at 3300, an ice-water layer the paper leaves free between
    # 1060 and 1370 — and again two constraints for three unknowns, so it is a
    # family, not an answer. Solving mass balance with C/MR² across that ice
    # range walks the core from nothing to 0.527 R:
    #   ice 1060 → no core at all
    #   ice 1215 → core 835 km (0.317 R) → 0.0849, and this is what ships
    #   ice 1370 → core 1388 km (0.527 R) → 0.389, and no mantle left
    # The two ends reproduce the paper's own limits — it puts the core "up to
    # ~50% of the total radius, representing up to 33% of Ganymede's mass", and
    # says it cannot exceed that "without the complete disappearance of the
    # mantle". The midpoint of the ice range is the shipped member because the
    # paper prefers none.
    #
    # That 834 km of "ice" is not ice. Ganymede's ocean is about as settled as
    # an unvisited ocean gets: Galileo found an induced magnetic field, and
    # Hubble then watched the auroral ovals rock by 2.0° ± 1.3° against the
    # 5.8° ± 1.3° a Ganymede without a conducting layer would give — the ocean
    # is what holds them still. Gravity cannot see any boundary inside the
    # water, so the stratigraphy is Vance's thermodynamic model, whose middle
    # case puts 70 km of ice I over a 375 km ocean over high-pressure ice VI
    # down to rock at 1803 km — within 5 km of the 1798 solved for above,
    # which is the check worth having, since the two came from different data.
    #
    # Taking those boundaries and the densities the phases actually have at
    # these pressures, ice I 920, ocean 1100, ice VI 1460:
    #   ice I  2632.7 → 2562.7 km → 0.0369
    #   ocean  2562.7 → 2187.7 km → 0.1977
    #   ice VI 2187.7 → 1798.0 km → 0.1922
    # which averages 1214 kg/m³ over the whole hydrosphere — the 1215 the
    # uniform solve used, arrived at from the phase diagram instead. So the
    # rock and metal below do not move; only the water above them is resolved.
    #
    # Each sublayer carries the hydrosphere's own 0.3324-0.5979 spread scaled
    # onto it, because what the moment of inertia is uncertain about is how
    # much water there is, not how it is stacked.
    "naif-503": BodyInterior(
        structure="differentiated",
        structure_source="gomez_casajus_2022",
        note="subsurface_ocean",
        layers=(
            Layer(
                role="ice_shell",
                mass_fraction=0.0369,
                mass_fraction_range=(0.0287, 0.0516),
                composition=(Component(WATER, 1.0, "anderson_1996"),),
                source="vance_2018",
                outer_radius_km=2632.7,
                derived=True,
                note="shell_thickness_modelled",
                state="solid",
            ),
            Layer(
                role="ocean",
                mass_fraction=0.1977,
                mass_fraction_range=(0.1538, 0.2766),
                composition=(Component(WATER, 1.0, "saur_2015"),),
                source="vance_2018",
                outer_radius_km=2562.7,
                derived=True,
                state="liquid",
                outer_temperature_range_k=ICE_OCEAN_INTERFACE_K,
                temperature_sources=("vance_2018",),
            ),
            Layer(
                role="ice_mantle",
                mass_fraction=0.1922,
                mass_fraction_range=(0.1495, 0.2689),
                composition=(Component(WATER, 1.0, "anderson_1996"),),
                source="vance_2018",
                outer_radius_km=2187.7,
                derived=True,
                state="solid",
            ),
            Layer(
                role="mantle",
                mass_fraction=0.4879,
                mass_fraction_range=(0.0131, 0.6680),
                composition=(Component(SILICATE, 1.0, "anderson_1996"),),
                source="gomez_casajus_2022",
                outer_radius_km=1798.0,
                derived=True,
                note="from_moment_of_inertia",
                state="solid",
            ),
            Layer(
                role="core",
                mass_fraction=0.0849,
                mass_fraction_range=(0.0, 0.389),
                composition=(Component(METAL, 1.0, "anderson_1996"),),
                source="gomez_casajus_2022",
                outer_radius_km=835.3,
                derived=True,
                note="core_size_disputed",
                state="liquid",
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
    #
    # That shell is not all frozen. Galileo's magnetometer found an induced
    # field at Callisto as well as at Europa, which needs a layer conducting
    # better than 0.02 S/m within 300 km of the surface, and nothing but salty
    # water does that on a body this cold. Vance's model puts 100 km of ice I
    # over a 132 km ocean over ice V, reaching rock at 2166 km — 76 km deeper
    # than the 2090 the moment of inertia gives, so the ice V is stretched to
    # meet it:
    #   ice I 2410.3 → 2310.3 km at 920  → 0.0599
    #   ocean 2310.3 → 2178.3 km at 1000 → 0.0777
    #   ice V 2178.3 → 2090.0 km at 1240 → 0.0583
    # 0.1958 against the 0.190 the uniform-1000 shell gave: a structured shell
    # is 3% heavier, which takes the interior below it from 2280 to 2263 kg/m³
    # and its rock fraction from 0.78 to 0.776. Nothing that shows, and the
    # difference is the honest one — an ocean and high-pressure ice are both
    # denser than the ice the two-layer solve assumed throughout.
    "naif-504": BodyInterior(
        structure="partially_differentiated",
        structure_source="anderson_2001_callisto",
        note="subsurface_ocean",
        layers=(
            Layer(
                role="ice_shell",
                mass_fraction=0.0599,
                composition=(Component(WATER, 1.0, "anderson_2001_callisto"),),
                source="vance_2018",
                outer_radius_km=2410.3,
                derived=True,
                note="shell_thickness_modelled",
                state="solid",
            ),
            Layer(
                role="ocean",
                mass_fraction=0.0777,
                composition=(Component(WATER, 1.0, "zimmer_2000"),),
                source="vance_2018",
                outer_radius_km=2310.3,
                derived=True,
                state="liquid",
                outer_temperature_range_k=ICE_OCEAN_INTERFACE_K,
                temperature_sources=("vance_2018",),
            ),
            Layer(
                role="ice_mantle",
                mass_fraction=0.0583,
                composition=(Component(WATER, 1.0, "anderson_2001_callisto"),),
                source="vance_2018",
                outer_radius_km=2178.3,
                derived=True,
                state="solid",
            ),
            Layer(
                role="bulk",
                mass_fraction=0.8042,
                composition=(
                    Component(SILICATE, 0.776, "anderson_2001_callisto"),
                    Component(WATER, 0.224, "anderson_2001_callisto"),
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
    # give: J₂ and C₂₂ put the moment of inertia at 0.341, and a re-analysis
    # of the same Cassini tracking searches the four-layer space directly,
    # coming out with a core of 2110 ± 76 km at 2528 ± 175 kg/m³ — quoted,
    # rather than solved for here. Its mass follows:
    #   (4/3)π(2110 km)³ × 2528 = 9.947e22 kg / 1.3452e23 → 0.7395
    # and the 465 km of H₂O left over has to average 1090 kg/m³ to make up
    # Titan's mass. That is the check worth having: the same paper derives an
    # ocean density of 1091 ± 107 kg/m³ from the Love number, by a route that
    # never touches this arithmetic.
    #
    # That coincidence is also what splits the hydrosphere. Gravity sees no
    # boundary inside the water — the paper could pin neither the ocean nor
    # the crust, and its solutions pile up against the 50 km floor it imposed
    # rather than converging. But if the whole 465 km averages 1090 and the
    # ocean *is* 1091, then the ice I above it, which is lighter, has to be
    # paid for by high-pressure ice below it, which is heavier, and the two
    # have to cancel. That is one equation, so one thickness still has to come
    # from outside: Vance's conductive case gives 120-149 km of ice I. Taking
    # 140 km at 920, ice VI at 1400 and the ocean at its measured 1091,
    #   ice I  2574.7 → 2434.7 km → 0.0755
    #   ocean  2434.7 → 2212.4 km → 0.1224
    #   ice VI 2212.4 → 2110.0 km → 0.0626
    # and the sum is 0.2605 by construction. Ice I between 120 and 149 km
    # walks the ocean over 207-256 km, which is the range each layer carries.
    # Thinner ice than that is not excluded by any of this; it is excluded by
    # nothing, which is why the shell keeps `shell_thickness_modelled`.
    #
    # 2528 kg/m³ is far too light for dry rock, so the core is hydrated or
    # porous or both — the same story as Enceladus, one order of magnitude up.
    "naif-606": BodyInterior(
        structure="differentiated",
        structure_source="iess_2012",
        note="subsurface_ocean",
        layers=(
            Layer(
                role="ice_shell",
                mass_fraction=0.0755,
                mass_fraction_range=(0.0652, 0.0801),
                # That the outer layer is water rather than light rock is the
                # moment of inertia's statement, not this paper's.
                composition=(Component(WATER, 1.0, "durante_2019"),),
                source="vance_2018",
                outer_radius_km=2574.73,
                derived=True,
                note="shell_thickness_modelled",
                state="solid",
            ),
            Layer(
                role="ocean",
                mass_fraction=0.1224,
                mass_fraction_range=(0.1140, 0.1413),
                composition=(Component(WATER, 1.0, "iess_2012"),),
                source="goossens_2024",
                outer_radius_km=2434.73,
                derived=True,
                state="liquid",
                outer_temperature_range_k=ICE_OCEAN_INTERFACE_K,
                temperature_sources=("vance_2018",),
            ),
            Layer(
                role="ice_mantle",
                mass_fraction=0.0626,
                mass_fraction_range=(0.0539, 0.0664),
                composition=(Component(WATER, 1.0, "durante_2019"),),
                source="goossens_2024",
                outer_radius_km=2212.4,
                derived=True,
                state="solid",
            ),
            Layer(
                role="core",
                mass_fraction=0.7395,
                mass_fraction_range=(0.7083, 0.7654),
                composition=(Component(SILICATE, 1.0, "goossens_2024"),),
                source="goossens_2024",
                outer_radius_km=2110.0,
                derived=True,
                note="hydrated_rock",
                state="solid",
            ),
        ),
    ),
    # Vesta, which was the asteroid with a metal core until somebody measured
    # the moment of inertia. Dawn's gravity and shape alone allow anything from
    # a small planet to a rock, and the model that stood for a decade took the
    # most-differentiated end of that range — a 110 km core at 7800 kg/m³ under
    # a 40 km basaltic crust, a sixth of Vesta in metal.
    #
    # The nutation and precession amplitudes in Dawn's tracking finally give
    # the moment of inertia directly, and it is C/MR² = 0.4208 ± 0.0047 — only
    # 6.6% below the 0.4505 of a body of uniform density. There is almost no
    # concentration towards the centre to explain, so there is almost no core:
    # the four-parameter inversion returns a crust 47 (+12/−13) km thick at
    # 2.70 g/cm³, a mantle of 4.1 g/cm³, and a core of 45 (+32/−32) km at
    # 5.6 g/cm³ inside a body of volumetric radius 261.3 km.
    #   crust  261.3 → 214.3 km at 2700 = 9.05e19 kg / 2.590e20 → 0.349
    #   core   (4/3)π(45.3 km)³ × 5600                          → 0.008
    #   mantle the remainder, which needs 4074 kg/m³            → 0.642
    # A core that is 0.8% of the body rather than 17%, and a mantle denser than
    # olivine — Vesta's interior is closer to a mesosiderite, metal and silicate
    # still mixed, than to a small Earth. Either it began to differentiate and
    # stopped, or it is the re-accreted debris of something larger; the paper
    # declines to choose, and both leave it `partially_differentiated`.
    #
    # The 45 km is a median with a 5-95% interval of 13 to 132 km, which at
    # the median density is 0.0002 to 0.21 of the body — so the *upper* end
    # still allows something like the old model. What it no longer allows is
    # calling that the answer, and the paper's own reading of the same
    # ensemble is that 90% of it has a core-mantle density contrast under
    # 1.7 g/cm³, which no metal core produces.
    #
    # The HED meteorites and the basaltic crust are unaffected: the crust is
    # thicker than the old model's and still the same rock. What went is the
    # core.
    "spkid-20000004": BodyInterior(
        structure="partially_differentiated",
        structure_source="park_2025_vesta",
        layers=(
            Layer(
                role="crust",
                mass_fraction=0.349,
                composition=(Component(SILICATE, 1.0, "ermakov_2014"),),
                source="park_2025_vesta",
                outer_radius_km=261.3,
                derived=True,
                state="solid",
            ),
            Layer(
                role="mantle",
                mass_fraction=0.642,
                composition=(Component(SILICATE, 1.0, "park_2025_vesta"),),
                source="park_2025_vesta",
                outer_radius_km=214.3,
                derived=True,
                note="from_moment_of_inertia",
                state="solid",
            ),
            Layer(
                role="core",
                mass_fraction=0.008,
                mass_fraction_range=(0.0002, 0.2083),
                composition=(Component(METAL, 1.0, "park_2025_vesta"),),
                source="park_2025_vesta",
                outer_radius_km=45.3,
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
    #
    # 48% ice by volume is also what the craters say, by a route with no
    # gravity in it. Ceres's craters have not relaxed away, which for twenty
    # years was read as an ice-poor crust; running the same finite-element
    # models with an ice rheology that lets impurities pin the grain
    # boundaries reverses it, and the crust that best fits the topography *and*
    # the gravity is ~90% ice at the surface grading to none at 117 km — a
    # mean near half by volume over the layer. So the shell's composition
    # stands, and what it is gains a history: a global ocean that froze from
    # the top down, concentrating its dirt downwards as it went.
    "naif-2000001": BodyInterior(
        structure="partially_differentiated",
        structure_source="park_2016",
        layers=(
            Layer(
                role="crust",
                mass_fraction=0.715,
                composition=(
                    Component(SILICATE, 0.77, "park_2016"),
                    Component(WATER, 0.23, "pamerleau_2024"),
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
    # of 400 ± 25 km at 2400 ± 200 kg/m³ under a water-ice envelope. The
    # paper's own band across the plausible moments of inertia puts the rock at
    # 56-66%, so the rock:ice ratio is close to 1:1 by mass.
    #
    # The topography only balances if the ice shell floats on something denser
    # and softer, and Beuthe weighs that something: requiring the shell to be
    # isostatic at minimum deviatoric stress splits the 164 km of H₂O into
    # 99 ± 23 km of ice over a 65 ± 30 km ocean, the first clear evidence of a
    # present-day ocean in Dione. Those two thicknesses land the rock at
    # 400.1 km without being told to, which is the check. Masses follow:
    #   shell 564.1 → 465.1 km at 920  → 0.278
    #   ocean 465.1 → 400.1 km at 1000 → 0.140
    #   core  the remainder, 2379 kg/m³ (the paper's 2400 ± 200) → 0.582
    # Supersedes the two-layer thermal model below.
    "naif-604": BodyInterior(
        structure="differentiated",
        structure_source="zannoni_2020",
        note="subsurface_ocean",
        layers=(
            Layer(
                role="ice_shell",
                mass_fraction=0.278,
                composition=(Component(WATER, 1.0, "zannoni_2020"),),
                source="beuthe_2016",
                outer_radius_km=564.1,
                derived=True,
                state="solid",
            ),
            Layer(
                role="ocean",
                mass_fraction=0.140,
                composition=(Component(WATER, 1.0, "zannoni_2020"),),
                source="beuthe_2016",
                outer_radius_km=465.1,
                derived=True,
                state="liquid",
                outer_temperature_range_k=ICE_OCEAN_INTERFACE_K,
                temperature_sources=("vance_2018",),
            ),
            Layer(
                role="core",
                mass_fraction=0.582,
                mass_fraction_range=(0.56, 0.66),
                composition=(Component(SILICATE, 1.0, "zannoni_2020"),),
                source="zannoni_2020",
                outer_radius_km=400.1,
                derived=True,
                state="solid",
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
                state="fluid",
            ),
        ),
        # A factor of five, which is the state of the question rather than a
        # sloppy model: standard adiabatic interiors land near 6000 K, and
        # models that drop the fully-convective assumption — which Uranus's
        # feeble internal heat flux invites — reach several times that. Voyager
        # 2 is the only visit either ice giant has had.
        centre_temperature_range_k=(6000.0, 28000.0),
        centre_temperature_sources=("scheibe_2019",),
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
                state="fluid",
            ),
        ),
        centre_temperature_range_k=(6000.0, 28000.0),
        centre_temperature_sources=("scheibe_2019",),
    ),
    # The Sun. Three zones with compositions and no masses: the solar model
    # paper tabulates abundances and the depth of the convective zone but not
    # how the Sun's mass divides between them, so these layers carry geometry
    # and chemistry only.
    #
    # Boundaries, both at fractions of R☉ = 695 700 km. The convective zone's
    # base is the model's 0.7138 — helioseismology's own 0.713 ± 0.001 agrees,
    # one of the better agreements in the subject. The core's top is 0.2, which
    # is the definition the gravity-mode work uses when it says g modes are the
    # only thing that probes down there; the same paper is why the core is
    # separated from the radiative zone at all, having found it spinning
    # several times faster than the zone around it.
    #
    # The interesting number is what 4.6 Gyr of fusion has done. The convective
    # zone is stirred well enough that its surface abundances are the whole
    # zone's — hydrogen 0.740, helium 0.243 — while at the centre helium has
    # gone from the 0.2725 the Sun formed with to 0.634, more than doubling.
    # Two caveats to read the bars with: the core's numbers are the centre's,
    # and helium falls outwards from there, so they are the extreme of that
    # layer rather than its average. And the radiative zone carries the Sun's
    # zero-age composition, because it is the part where nothing has burned and
    # nothing has mixed — a statement about what the layer *is*, not a fourth
    # column in the model's table.
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
                state="plasma",
            ),
            Layer(
                role="radiative_zone",
                mass_fraction=None,
                composition=(
                    Component(HYDROGEN, 0.7087, "bahcall_2005"),
                    Component(HELIUM, 0.2725, "bahcall_2005"),
                    Component(HEAVY_ELEMENTS, 0.0188, "bahcall_2005"),
                ),
                source="bahcall_2005",
                outer_radius_km=496590.0,
                derived=True,
                state="plasma",
                # Where convection starts, and the one place in the Sun a
                # temperature is quoted to two figures rather than a bracket:
                # the standard model and helioseismology agree here.
                outer_temperature_k=2.0e6,
                temperature_sources=("bahcall_2005",),
            ),
            Layer(
                role="core",
                mass_fraction=None,
                composition=(
                    Component(HELIUM, 0.634, "bahcall_2005"),
                    Component(HYDROGEN, 0.346, "bahcall_2005"),
                    Component(HEAVY_ELEMENTS, 0.020, "bahcall_2005"),
                ),
                source="garcia_2007",
                outer_radius_km=139140.0,
                derived=True,
                state="plasma",
                # 0.2 R☉, where fusion has effectively stopped — the reason the
                # core is drawn as ending there at all.
                outer_temperature_k=7.0e6,
                temperature_sources=("bahcall_2005",),
            ),
        ),
        # The best-constrained centre of any body here: helioseismology and the
        # neutrino flux both pin it, so the bracket is model spread rather than
        # uncertainty about the Sun.
        centre_temperature_range_k=(15.5e6, 15.7e6),
        centre_temperature_sources=("bahcall_2005",),
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
            # Where the ocean's top sits is a thermal model, not a measurement,
            # and the model is the one that produced the 0.95 g/cc hydrosphere
            # the rock fraction above was solved against — so the two have to
            # agree, and they do. A conductive shell freezing for 4.5 Gyr
            # leaves ~100 km of water under ~250 km of ice; over the 348 km of
            # hydrosphere the mass balance allows, 248 of ice at 920 and 100 of
            # water at 1050 average 949 kg/m³, which is that same 0.95. The
            # ocean could be anywhere from 20 to 200 km thick on the other
            # assumptions the review lists, hence the range.
            Layer(
                role="ice_shell",
                mass_fraction=0.242,
                composition=(Component(WATER, 1.0, "nimmo_2025"),),
                source="nimmo_2025",
                outer_radius_km=1188.3,
                derived=True,
                note="shell_thickness_modelled",
                state="solid",
            ),
            Layer(
                role="ocean",
                mass_fraction=0.078,
                mass_fraction_range=(0.016, 0.155),
                composition=(Component(WATER, 1.0, "nimmo_2025"),),
                source="nimmo_2025",
                outer_radius_km=940.0,
                derived=True,
                state="liquid",
                outer_temperature_range_k=ICE_OCEAN_INTERFACE_K,
                temperature_sources=("vance_2018",),
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
    # The four giants and the Sun carry no note: `structure="fluid"` says it
    # all, and the frontend derives its "no solid surface" sentence from that
    # field directly.
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
    #
    # And most of Jupiter is that metallic envelope. Squeeze hydrogen past
    # about a megabar and it stops being a molecular gas and starts conducting
    # like a metal, which is what generates the magnetic field; the planet is
    # then only nominally "an envelope". Nettelmann's model J11-4a puts its
    # boundary at 400 GPa, which sits at 0.7355 of Jupiter's mean radius
    # (69 911 km, so 51 400 km) and — the number worth having — at the mass
    # coordinate 227.16 of 317.83 M⊕. So the molecular envelope is only
    #   (317.83 - 227.16) / 317.83 = 0.285
    # of the planet, and the metallic hydrogen under it is 0.715 less whatever
    # the dilute core takes, 0.665.
    #
    # Where to draw that line is a modelling choice, not a phase boundary:
    # above the critical point hydrogen dissociates gradually, and Militzer's
    # models put the change anywhere from 0.72 to 0.83 r_J with a helium rain
    # layer in the middle. Hence `diffuse` on the metallic layer too — the
    # radius is where the character changes, not where a surface is.
    "naif-599": BodyInterior(
        structure="fluid",
        structure_source="wahl_2017",
        layers=(
            Layer(
                role="envelope",
                mass_fraction=0.285,
                composition=(
                    Component(HYDROGEN, 0.750, "wahl_2017"),
                    Component(HELIUM, 0.233, "wahl_2017"),
                    Component(HEAVY_ELEMENTS, 0.017, "wahl_2017"),
                ),
                source="nettelmann_2012",
                outer_radius_km=71492.0,
                derived=True,
                state="fluid",
            ),
            # Helium-rich, and that is where the helium the Galileo probe did
            # not find has gone: below about a megabar helium stops mixing
            # with hydrogen and rains out, so the molecular envelope reads
            # Y = 0.233 against a protosolar 0.278 and this layer has to carry
            # the difference, Ỹ = 0.2957 in Militzer's fit, or Y = 0.300 once
            # the heavy elements are taken back out.
            Layer(
                role="metallic_hydrogen",
                mass_fraction=0.665,
                mass_fraction_range=(0.636, 0.693),
                composition=(
                    Component(HYDROGEN, 0.684, "militzer_2022"),
                    Component(HELIUM, 0.300, "militzer_2022"),
                    Component(HEAVY_ELEMENTS, 0.016, "militzer_2022"),
                ),
                source="nettelmann_2012",
                outer_radius_km=51400.0,
                derived=True,
                diffuse=True,
                state="fluid",
            ),
            # Half the planet's radius: 0.50 r_J is what the dilute-core models
            # need to fit Juno's J₄, against 0.15 for the compact core they
            # replace. `diffuse` because that is where the enrichment fades,
            # not a surface — and the 0.050 below is the heavy elements it
            # carries, not the mass inside 35 746 km. Half of Jupiter is inside
            # that radius; nearly all of it is hydrogen and helium, and that
            # hydrogen is counted in the metallic layer above. Do not subtract
            # one from the other.
            Layer(
                role="core",
                mass_fraction=0.050,
                mass_fraction_range=(0.022, 0.079),
                composition=(Component(HEAVY_ELEMENTS, 1.0, "wahl_2017"),),
                source="wahl_2017",
                outer_radius_km=35746.0,
                derived=True,
                diffuse=True,
            ),
        ),
        # The centre rather than a boundary, because a dilute core has none.
        # The two ends are two eras: the low one is the classical three-layer
        # adiabat, the high one a post-Juno dilute-core interior. The gap
        # between them is an open question, not an error bar.
        centre_temperature_range_k=(15000.0, 36000.0),
        centre_temperature_sources=("guillot_2005", "helled_2024"),
    ),
    # Saturn, from the Grand Finale orbits. The gravity rules out uniform
    # rotation outright, and once differential rotation is in the models the
    # core lands at 15.0-18.2 M⊕ of Saturn's 95.16 — 0.158-0.191.
    #
    # The rings then say where that mass sits, and it is not in a ball. Waves
    # in the C ring are driven by Saturn's own pulsation modes, and the modes
    # observed are gravity modes, which only propagate through gas that is
    # stable against convection — a composition gradient. Fitting their
    # frequencies needs that gradient to reach 0.60 of the planet's radius
    # while holding ~17 M⊕ of ice and rock, which is the same mass the gravity
    # gives at three times the radius the gravity's compact core assumed.
    # So Saturn's core is dilute like Jupiter's, and the radius below is where
    # the enrichment fades rather than a surface.
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
                mass_fraction=0.821,
                mass_fraction_range=(0.809, 0.842),
                composition=(
                    Component(HYDROGEN, 0.687, "iess_2019"),
                    Component(HELIUM, 0.274, "iess_2019", (0.055, 0.274)),
                    Component(HEAVY_ELEMENTS, 0.039, "iess_2019", (0.017, 0.061)),
                ),
                source="iess_2019",
                outer_radius_km=58232.0,
                state="fluid",
            ),
            Layer(
                role="core",
                mass_fraction=0.179,
                mass_fraction_range=(0.158, 0.191),
                composition=(Component(HEAVY_ELEMENTS, 1.0, "iess_2019"),),
                source="mankovich_2021",
                outer_radius_km=34939.0,
                derived=True,
                diffuse=True,
            ),
        ),
        centre_temperature_range_k=(8000.0, 12000.0),
        centre_temperature_sources=("guillot_2005", "helled_2024"),
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
# of water ice, and the model returns a 29 km core carrying 0.058% of the
# mass — a rock the size of a small moon at the centre of a ball of ice 531 km
# across. It ships anyway. The paper says outright that assuming Tethys
# differentiated at all is questionable, which is what `structure` and the
# note are for; a core too small to see is still the model's answer, and
# dropping it would leave the same claim looking like a measurement of a
# uniform body.
INTERIOR_FACTS["naif-603"] = BodyInterior(
    structure="partially_differentiated",
    structure_source="hussmann_2006",
    layers=(
        Layer(
            role="ice_shell",
            mass_fraction=0.99942,
            composition=(Component(WATER, 1.0, "hussmann_2006"),),
            source="hussmann_2006",
            outer_radius_km=531.0,
            note="from_bulk_density",
            state="solid",
        ),
        Layer(
            role="core",
            mass_fraction=0.00058,
            composition=(Component(SILICATE, 1.0, "hussmann_2006"),),
            source="hussmann_2006",
            outer_radius_km=29.0,
            derived=True,
            note="from_bulk_density",
            state="solid",
        ),
    ),
)
