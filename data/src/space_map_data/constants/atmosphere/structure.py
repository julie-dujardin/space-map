"""Named vertical layers of each atmosphere — the panel's cross-section.

`facts.py` states one condition per body: the pressure and the mixing ratios at
a single level. This is the axis that level sits on. A layer boundary is almost
always a turning point in temperature rather than a surface — a tropopause is
where the profile stops cooling — so what a source pins is sometimes an
altitude, sometimes a pressure, rarely both; every field here is optional for
that reason, and `pressure_source` exists because the two often come from
different works.

Composition stays in `facts.py` wherever the layer is well mixed, which is
everything below the homopause: repeating the body's own numbers per layer
would be the same measurement written five times, and would drift. A layer
carries its own composition only where the literature measures one that
differs — Titan's methane, which halves between the surface and the
stratosphere.

Gas giants have no surface, so their altitudes hang off the 1 bar level and
run negative below it; `datum` says which zero a body uses. They also need
`datum_temperature_k`, because a layer is only readable as a layer once both
its ends are known and the lowest one's base is the datum — everywhere else
that base is the body's own surface reading and the export takes it from
there.
"""

from typing import NamedTuple

from space_map_data.constants.atmosphere.facts import Species


# `AtmosphereLayer.role` values, lowest first.
LAYER_ROLES = frozenset(
    {
        "boundary_layer",  # Pluto's few km of surface-driven convection
        "troposphere",
        "stratosphere",
        "mesosphere",
        "thermosphere",
        "exosphere",
        # Stellar. Named for how the gas radiates rather than for how its
        # temperature turns, which is why a photosphere is 500 km and the
        # corona has no top at all.
        "photosphere",
        "chromosphere",
        "transition_region",
        "corona",
    }
)

# `BodyStructure.datum` values — what altitude 0 means.
DATUMS = frozenset({"surface", "one_bar", "photosphere"})

# `AtmosphereLayer.note` / `BodyStructure.note` values. Same contract as the
# atmosphere and interior facts: the pipeline ships a key, the frontend ships
# the sentence, so the prose stays translatable.
NOTES = frozenset(
    {
        "well_mixed",  # below the homopause — the body's composition holds
        "heterosphere",  # above it — species sort by mass, no single mixture
        "no_inversion",  # CO₂ atmospheres warm no stratosphere above them
        "nightside_cryosphere",
        "seasonal_dust",
        "weakly_defined",  # named in the literature, barely there in the data
        "diffuse_top",  # fades out rather than ending
        "haze_layers",
        "cloud_deck",
        "exobase",
    }
)


class AtmosphereLayer(NamedTuple):
    """One named region, described by its top. The base is the layer below's
    top, and the lowest layer's base is the body's datum."""

    role: str
    top_km: float | None
    top_pressure_pa: float | None
    source: str  # backs the boundary and the layer's existence
    top_temperature_k: float | None = None
    # Where the boundary actually sits — Earth's tropopause runs 9 km over the
    # poles to 17 km over the equator, and drawing 11 km without saying so
    # claims a sharpness the atmosphere does not have.
    top_km_range: tuple[float, float] | None = None
    # Likewise for the reading: a thermosphere's temperature is a range over
    # latitude and solar cycle, not an error bar on one number.
    top_temperature_range_k: tuple[float, float] | None = None
    # Set where the pressure comes from a different work than the altitude.
    pressure_source: str | None = None
    # And the mirror of it: set where the height comes from a different work
    # than the temperature that defines the boundary.
    altitude_source: str | None = None
    # In the body's `facts.py` composition unit. Empty means well mixed: read
    # the body's composition instead.
    composition: tuple[Species, ...] = ()
    note: str | None = None


class BodyStructure(NamedTuple):
    datum: str
    layers: tuple[AtmosphereLayer, ...]  # lowest first
    # The temperature at altitude 0, which is the base of the lowest layer.
    # Only for bodies whose datum is not a surface: everywhere else this is
    # the body's measured surface temperature, and the export reads it from
    # constants/temperature rather than restating it here.
    datum_temperature_k: float | None = None
    datum_temperature_source: str | None = None
    # Where mixing stops and diffusive separation begins — above it the body's
    # single composition stops meaning anything. Stated in pressure on the
    # giants, where it is a level in a photochemical model rather than a
    # height anyone measured.
    homopause_km: float | None = None
    homopause_pressure_pa: float | None = None
    homopause_source: str | None = None
    # For envelopes with no boundaries to name: how fast the density falls,
    # rather than where it stops. This is the whole vertical structure of a
    # surface-bounded exosphere. It is only meaningful where one species
    # dominates — the Moon's and Mercury's exospheres are mixtures whose
    # species differ by an order of magnitude in scale height, so they have
    # none rather than an average of numbers that describe nothing.
    scale_height_km: float | None = None
    scale_height_source: str | None = None
    note: str | None = None


ATMOSPHERE_STRUCTURE: dict[str, BodyStructure] = {
    # The Sun. Heights run from optical depth 1 at 500 nm, the surface every
    # other solar number is quoted against. The photosphere's top is its
    # temperature minimum rather than a density boundary: VAL-C puts that at
    # 515 km and 4170 K, and NSSDCA's 0.868 mb row is the same level's
    # pressure. Everything above it gets hotter, which is the part nobody has
    # fully explained.
    "naif-10": BodyStructure(
        datum="photosphere",
        layers=(
            AtmosphereLayer(
                role="photosphere",
                top_km=500.0,
                top_pressure_pa=86.8,
                source="val_c_1981",
                top_temperature_k=4170.0,
                pressure_source="nssdc_sun",
            ),
            AtmosphereLayer(
                role="chromosphere",
                top_km=2500.0,
                top_pressure_pa=None,
                source="wiki_solar_atm",
                top_temperature_k=20000.0,
            ),
            # ~200 km across, and the temperature runs from 20 000 K to a
            # million over it.
            AtmosphereLayer(
                role="transition_region",
                top_km=2700.0,
                top_pressure_pa=None,
                source="wiki_solar_atm",
                top_temperature_k=1.0e6,
            ),
            AtmosphereLayer(
                role="corona",
                top_km=None,
                top_pressure_pa=None,
                source="wiki_solar_atm",
                top_temperature_k=1.5e6,
                note="diffuse_top",
            ),
        ),
    ),
    # Venus. The troposphere holds ~99% of the mass and ends in the cloud deck
    # the planet is photographed as; above it the profile just keeps cooling to
    # the 95-120 km mesopause, because a CO₂ atmosphere has no ozone-like
    # absorber to warm a stratosphere. Robinson & Catling's 0.1 bar tropopause
    # explicitly excludes Venus and Mars for that reason, and the downloaded
    # VIRA profile agrees: its only temperature minimum is up at 1.4e-4 bar.
    # The thermosphere is a dayside word — the night side is ~100 K and gets
    # called a cryosphere.
    "naif-299": BodyStructure(
        datum="surface",
        layers=(
            AtmosphereLayer(
                role="troposphere",
                top_km=65.0,
                top_pressure_pa=1.0e4,
                source="seiff_1985",
                top_temperature_k=245.0,
                note="cloud_deck",
            ),
            AtmosphereLayer(
                role="mesosphere",
                top_km=120.0,
                top_pressure_pa=None,
                source="limaye_2018",
                top_temperature_k=165.0,
                top_km_range=(95.0, 120.0),
                note="no_inversion",
            ),
            AtmosphereLayer(
                role="thermosphere",
                top_km=220.0,
                top_pressure_pa=None,
                source="limaye_2018",
                top_temperature_k=300.0,
                note="nightside_cryosphere",
            ),
            AtmosphereLayer(
                role="exosphere",
                top_km=None,
                top_pressure_pa=None,
                source="limaye_2018",
                note="diffuse_top",
            ),
        ),
        # CO₂ below, atomic oxygen from ~140 km, helium above ~170 km at
        # night: three different atmospheres stacked in 40 km.
        homopause_km=130.0,
        homopause_source="niemann_1980_venus",
    ),
    # Earth, on the US Standard Atmosphere 1976 breakpoints — the tropopause
    # at 11 km, the isothermal stratopause layer topping out at 51 km, and the
    # model's own ceiling at 84.852 km for the mesopause. The tropopause range
    # is the real one: 9 km at the poles, 17 km at the equator, where the cold
    # point sits at almost exactly 0.1 bar.
    "naif-399": BodyStructure(
        datum="surface",
        layers=(
            AtmosphereLayer(
                role="troposphere",
                top_km=11.0,
                top_pressure_pa=22632.0,
                source="us_standard_1976",
                top_temperature_k=216.65,
                top_km_range=(9.0, 17.0),
                note="well_mixed",
            ),
            AtmosphereLayer(
                role="stratosphere",
                top_km=51.0,
                top_pressure_pa=66.939,
                source="us_standard_1976",
                top_temperature_k=270.65,
            ),
            AtmosphereLayer(
                role="mesosphere",
                top_km=84.852,
                top_pressure_pa=0.3734,
                source="us_standard_1976",
                top_temperature_k=186.87,
            ),
            # The top moves with the Sun: 500 km at solar minimum, 1000 km at
            # maximum, which is also why low-orbit satellites decay in bursts.
            # The temperature moves with it — Arecibo reads 800-1500 K at the
            # thermopause over a cycle.
            # The pressure is the standard atmosphere's at the nominal 600 km,
            # not at the moving thermopause. Do not read a height off this and
            # the mesopause by interpolating between them: the scale height
            # more than triples across the thermosphere, and doing so puts the
            # 100 km level — the one altitude here everybody knows — at 167.
            AtmosphereLayer(
                role="thermosphere",
                top_km=600.0,
                top_pressure_pa=8.213e-8,
                source="wiki_thermopause",
                top_temperature_k=1000.0,
                top_km_range=(500.0, 1000.0),
                top_temperature_range_k=(800.0, 1500.0),
                pressure_source="us_standard_atmosphere_1976",
                note="heterosphere",
            ),
            AtmosphereLayer(
                role="exosphere",
                top_km=10000.0,
                top_pressure_pa=None,
                source="wiki_earth_atm",
                note="diffuse_top",
            ),
        ),
        homopause_km=100.0,
        homopause_source="wiki_earth_atm",
    ),
    # Mars. Same shape as Venus and for the same reason — no stratosphere, so
    # the troposphere runs straight into a mesosphere. Boundaries and the
    # mesopause pressure band (0.01-0.001 Pa) are Haberle's; the pressures at
    # 40 and 230 km are read off the Mars Climate Database profile the PSG
    # downloader pulls, which lands inside that band at the mesopause.
    "naif-499": BodyStructure(
        datum="surface",
        layers=(
            AtmosphereLayer(
                role="troposphere",
                top_km=40.0,
                top_pressure_pa=10.2,
                source="haberle_2015",
                top_temperature_k=162.0,
                pressure_source="millour_2015",
                note="seasonal_dust",
            ),
            AtmosphereLayer(
                role="mesosphere",
                top_km=100.0,
                top_pressure_pa=6.0e-3,
                source="haberle_2015",
                top_temperature_k=110.0,
                pressure_source="millour_2015",
                note="no_inversion",
            ),
            AtmosphereLayer(
                role="thermosphere",
                top_km=230.0,
                top_pressure_pa=4.1e-8,
                source="haberle_2015",
                top_temperature_k=200.0,
                pressure_source="millour_2015",
                note="heterosphere",
            ),
            AtmosphereLayer(
                role="exosphere",
                top_km=None,
                top_pressure_pa=None,
                source="haberle_2015",
                note="diffuse_top",
            ),
        ),
        # MAVEN finds argon and nitrogen still tracking their surface ratios
        # to CO₂ down at the deepest dips, which puts the homopause here or a
        # little lower; it moves with how much dust is heating the air below.
        homopause_km=130.0,
        homopause_source="mahaffy_2015",
    ),
    # Jupiter, referenced to the 1 bar level. The troposphere continues below
    # it with no floor — it turns into the interior rather than meeting one.
    # Above 320 km the hydrocarbons stop shielding and the temperature runs
    # away to ~1000 K, the same unexplained heating every giant shows.
    "naif-599": BodyStructure(
        datum="one_bar",
        layers=(
            AtmosphereLayer(
                role="troposphere",
                top_km=50.0,
                top_pressure_pa=1.0e4,
                source="seiff_1998",
                top_temperature_k=110.0,
            ),
            AtmosphereLayer(
                role="stratosphere",
                top_km=320.0,
                top_pressure_pa=0.1,
                source="wiki_jupiter_atm",
                top_temperature_k=200.0,
            ),
            AtmosphereLayer(
                role="thermosphere",
                top_km=1000.0,
                top_pressure_pa=1.0e-4,
                source="yelle_miller_2004",
                top_temperature_k=1000.0,
                note="heterosphere",
            ),
            AtmosphereLayer(
                role="exosphere",
                top_km=5000.0,
                top_pressure_pa=None,
                source="wiki_jupiter_atm",
                note="diffuse_top",
            ),
        ),
        # 165 +/- 5 K. Lindal's Table 2 gives all four giants at 1 bar from
        # their Voyager and Pioneer occultations, so the four data below come
        # from one method and one set of assumed H/He mixes rather than from
        # four papers that each define the level slightly differently.
        datum_temperature_k=165.0,
        datum_temperature_source="lindal_1992",
        homopause_km=320.0,
        homopause_source="yelle_miller_2004",
    ),
    # Saturn. The tropopause is Voyager 2's ingress profile, whose Table I is
    # pressure, temperature and height above 1 bar together — the temperature
    # minimum is 82.0 K at 60 mbar, 106 km up. The 80-87 K width is that
    # profile's own equator-to-south-pole spread; Cassini/CIRS later put the
    # boundary nearer 80 mbar (Del Genio et al. 2009). Above it the middle
    # atmosphere is one region — radiative control from the tropopause to a
    # few 10⁻⁵ mbar — so no separate mesopause is claimed.
    "naif-699": BodyStructure(
        datum="one_bar",
        layers=(
            AtmosphereLayer(
                role="troposphere",
                top_km=106.0,
                top_pressure_pa=6.0e3,
                source="lindal_1985",
                top_temperature_k=82.0,
                top_temperature_range_k=(80.0, 87.0),
            ),
            # No source states this boundary's height, so it is read off the
            # two altitudes Strobel does pin — peak cooling at 870 km and
            # 70 nbar, peak heating at 1450 km and 0.65 nbar — as the level
            # where 10 nbar falls between them:
            #   870 + 530·ln(70/10)/ln(70/0.65) ≈ 1090 km
            AtmosphereLayer(
                role="stratosphere",
                top_km=1090.0,
                top_pressure_pa=1.0e-3,
                source="strobel_2018",
                top_temperature_k=150.0,
                pressure_source="fletcher_2018",
                note="weakly_defined",
            ),
            # Hotter at the poles than the equator, which is backwards for
            # solar heating and is the giants' unsolved energy-crisis problem.
            AtmosphereLayer(
                role="thermosphere",
                top_km=2800.0,
                top_pressure_pa=None,
                source="koskinen_2013",
                top_temperature_k=400.0,
                top_km_range=(2700.0, 3000.0),
                top_temperature_range_k=(370.0, 590.0),
                note="exobase",
            ),
            AtmosphereLayer(
                role="exosphere",
                top_km=None,
                top_pressure_pa=None,
                source="koskinen_2013",
                note="diffuse_top",
            ),
        ),
        # 134 +/- 4 K. Lindal's own ingress profile reads 134.8 K at the
        # 1000 mbar row of the same table the tropopause above comes from.
        datum_temperature_k=134.0,
        datum_temperature_source="lindal_1992",
        # Published as a band, 0.01-0.1 µbar; the middle of it is taken here.
        homopause_pressure_pa=3.0e-3,
        homopause_source="strobel_2018",
    ),
    # Uranus. The stratosphere is 4000 km deep — eighty Earth stratospheres —
    # because the gravity is low and the methane above the tropopause absorbs
    # over that whole span. The 800-850 K thermosphere reaches a quarter of the
    # planet's radius and drags on the rings.
    "naif-799": BodyStructure(
        datum="one_bar",
        layers=(
            AtmosphereLayer(
                role="troposphere",
                top_km=50.0,
                top_pressure_pa=1.0e4,
                source="lunine_1993",
                top_temperature_k=53.0,
            ),
            AtmosphereLayer(
                role="stratosphere",
                top_km=4000.0,
                top_pressure_pa=1.0e-5,
                source="lunine_1993",
                top_temperature_k=800.0,
            ),
            AtmosphereLayer(
                role="thermosphere",
                top_km=6500.0,
                top_pressure_pa=None,
                source="herbert_sandel_1999",
                top_temperature_k=850.0,
                top_temperature_range_k=(800.0, 850.0),
                note="exobase",
            ),
            AtmosphereLayer(
                role="exosphere",
                top_km=None,
                top_pressure_pa=None,
                source="herbert_sandel_1999",
                note="diffuse_top",
            ),
        ),
        # 76 +/- 2 K.
        datum_temperature_k=76.0,
        datum_temperature_source="lindal_1992",
        # Barely mixed at all: Uranus's stratosphere is stagnant enough to
        # hold the methane homopause down at 0.07 mbar, three orders of
        # magnitude deeper than Neptune's.
        homopause_pressure_pa=7.0,
        homopause_source="moses_2018",
    ),
    # Neptune, from Voyager 2's radio occultation: 72±2 K at the 1 bar level,
    # and the tropopause 40 km above it at ~100 mbar and 52±2 K. The
    # stratosphere above is still climbing at the top of that profile — 130±12
    # K at 0.3 mbar — and does not stop until the 750 K thermosphere, which is
    # the outlier of the four giants: Neptune gets a thousandth of Earth's
    # sunlight and is as hot up there as Uranus.
    #
    # Nothing measures a temperature between the two, though: Lindal's
    # occultation ends at 0.3 mbar and 130 ± 12 K with the profile still
    # climbing, and the UVS picks it up again only where it is already
    # hundreds of kelvin. The heights below are real; the shape between them
    # is not known.
    "naif-899": BodyStructure(
        datum="one_bar",
        layers=(
            AtmosphereLayer(
                role="troposphere",
                top_km=40.0,
                top_pressure_pa=1.0e4,
                source="lindal_1992",
                top_temperature_k=52.0,
                top_temperature_range_k=(50.0, 54.0),
            ),
            # Placed at the homopause, the way Saturn's is: on a giant the
            # stratosphere has no temperature turning point to end on, and the
            # level where mixing stops is the one thing anyone measured up
            # there. Voyager's UVS puts it at 400-500 km, and the pressure
            # Moses's photochemistry gives sits inside the same band.
            AtmosphereLayer(
                role="stratosphere",
                top_km=450.0,
                top_pressure_pa=8.0e-3,
                source="broadfoot_1989",
                top_km_range=(400.0, 500.0),
                pressure_source="moses_2018",
                note="weakly_defined",
            ),
            # Neptune's is the shortest thermosphere of the four giants —
            # Uranus's exobase sits at 6600 km on the same plot — and it is
            # nearly isothermal, at 750 K from about 2000 km up.
            AtmosphereLayer(
                role="thermosphere",
                top_km=4000.0,
                top_pressure_pa=None,
                source="broadfoot_1989",
                top_temperature_k=750.0,
                top_temperature_range_k=(600.0, 900.0),
                altitude_source="melin_2020",
                note="exobase",
            ),
            AtmosphereLayer(
                role="exosphere",
                top_km=None,
                top_pressure_pa=None,
                source="wiki_neptune",
                note="diffuse_top",
            ),
        ),
        # 72 +/- 2 K, the value the paragraph above opens on.
        datum_temperature_k=72.0,
        datum_temperature_source="lindal_1992",
        homopause_pressure_pa=8.0e-3,
        homopause_source="moses_2018",
    ),
    # Titan, from HASI's own descent profile — the only planetary atmosphere
    # besides Earth's whose whole structure was measured by one instrument
    # falling through it. Methane is the one composition that genuinely
    # changes between layers: 5.65% at the surface, constant to ~7 km, then
    # falling to a constant 1.48% through the stratosphere as it condenses
    # out. HASI found the mesosphere nearly absent where models wanted one.
    "naif-606": BodyStructure(
        datum="surface",
        layers=(
            AtmosphereLayer(
                role="troposphere",
                top_km=44.0,
                top_pressure_pa=1.0e4,
                source="huygens_hasi",
                top_temperature_k=70.4,
                pressure_source="robinson_catling_2014",
                composition=(Species("CH4", 0.0565, "niemann_2010"),),
            ),
            AtmosphereLayer(
                role="stratosphere",
                top_km=250.0,
                top_pressure_pa=1.0,
                source="huygens_hasi",
                top_temperature_k=186.0,
                pressure_source="nixon_2024",
                composition=(Species("CH4", 0.0148, "niemann_2010"),),
            ),
            AtmosphereLayer(
                role="mesosphere",
                top_km=500.0,
                top_pressure_pa=0.1,
                source="huygens_hasi",
                top_temperature_k=152.0,
                pressure_source="nixon_2024",
                note="weakly_defined",
            ),
            AtmosphereLayer(
                role="thermosphere",
                top_km=1200.0,
                top_pressure_pa=None,
                source="huygens_hasi",
                top_temperature_k=170.0,
                note="heterosphere",
            ),
            AtmosphereLayer(
                role="exosphere",
                top_km=1500.0,
                top_pressure_pa=None,
                source="huygens_hasi",
                note="exobase",
            ),
        ),
    ),
    # Pluto. There is no troposphere to speak of — New Horizons found a
    # boundary layer only 4 km deep, and not everywhere. Above it methane
    # warms the air by 2-6 K per kilometre to a stratopause near 30 km, and
    # then it cools again: no thermosphere, because at 39 AU there is nothing
    # to heat one. The haze is layered all the way through.
    "naif-999": BodyStructure(
        datum="surface",
        layers=(
            AtmosphereLayer(
                role="boundary_layer",
                top_km=4.0,
                top_pressure_pa=None,
                source="hinson_2017",
                top_temperature_k=37.0,
                note="weakly_defined",
            ),
            AtmosphereLayer(
                role="stratosphere",
                top_km=30.0,
                top_pressure_pa=None,
                source="gladstone_2016",
                top_temperature_k=106.0,
                top_km_range=(20.0, 40.0),
            ),
            AtmosphereLayer(
                role="mesosphere",
                top_km=200.0,
                top_pressure_pa=None,
                source="gladstone_2016",
                top_temperature_k=80.0,
                note="haze_layers",
            ),
            AtmosphereLayer(
                role="exosphere",
                top_km=1700.0,
                top_pressure_pa=None,
                source="gladstone_2016",
                note="exobase",
            ),
        ),
    ),
    # Triton. Sunlight on the nitrogen ice drives 8 km of convection and
    # nothing above it turns over again, so a troposphere sits directly under
    # a thermosphere. The exobase is at 870 km — a third of the moon's radius
    # of atmosphere above 1.5 Pa of surface pressure.
    "naif-801": BodyStructure(
        datum="surface",
        layers=(
            AtmosphereLayer(
                role="troposphere",
                top_km=8.0,
                top_pressure_pa=None,
                source="wiki_triton_atm",
                top_temperature_k=36.0,
            ),
            AtmosphereLayer(
                role="thermosphere",
                top_km=850.0,
                top_pressure_pa=None,
                source="strobel_zhu_2017",
                top_temperature_k=95.0,
            ),
            AtmosphereLayer(
                role="exosphere",
                top_km=870.0,
                top_pressure_pa=None,
                source="wiki_triton_atm",
                note="exobase",
            ),
        ),
    ),
    # Callisto, and the shape a surface-bounded exosphere takes here: one
    # layer with no top, described by how fast it thins instead. Galileo's
    # near-infrared spectrometer caught the CO₂ airglow in a single limb scan,
    # and an isothermal fit at 150 K gives 23 km. The emission faded into the
    # noise near 100 km, which is where the instrument stopped rather than
    # where the gas does.
    "naif-504": BodyStructure(
        datum="surface",
        layers=(
            AtmosphereLayer(
                role="exosphere",
                top_km=None,
                top_pressure_pa=None,
                source="carlson_1999",
                note="diffuse_top",
            ),
        ),
        scale_height_km=23.0,
        scale_height_source="carlson_1999",
    ),
}
